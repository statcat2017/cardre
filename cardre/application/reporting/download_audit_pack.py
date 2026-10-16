"""Download a registered project- and run-scoped audit archive."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cardre.application.ports.unit_of_work import UnitOfWorkFactory
from cardre.domain.errors import CardreError, ErrorCode

VERIFY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class DownloadableAuditPack:
    export_id: str
    run_id: str
    file_name: str
    file_path: Path
    delete_after_download: bool = False
    media_type: str = "application/zip"


class DownloadAuditPack:
    """Resolve only an audit pack registered for the requested project/run."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        project_root_factory: Callable[[str], Path],
    ) -> None:
        self._uow_factory = uow_factory
        self._project_root_factory = project_root_factory

    def __call__(self, project_id: str, run_id: str, export_id: str) -> DownloadableAuditPack:
        with self._uow_factory.read_only(project_id) as uow:
            if uow.runs.get(run_id) is None:
                raise CardreError(
                    f"Run {run_id!r} not found.",
                    code=ErrorCode.RUN_NOT_FOUND,
                    context={"run_id": run_id},
                )
            export = next(
                (
                    item for item in uow.exports.list_for_run(run_id)
                    if item.export_id == export_id and item.export_type == "audit_pack"
                ),
                None,
            )
            if export is None:
                raise _export_not_found(export_id, run_id)
            stored_path = Path(export.path)

        root = Path(self._project_root_factory(project_id)).resolve()
        if not stored_path.is_absolute():
            stored_path = root / stored_path
        temporary_path: Path | None = None
        try:
            path = stored_path.resolve(strict=True)
            path.relative_to(root)
            exports_root = (root / "exports").resolve()
            exports_root.relative_to(root)
            relative_to_exports = path.relative_to(exports_root)
            if not relative_to_exports.parts:
                raise ValueError("Audit pack path must be below the exports directory.")
            if path.is_file() and zipfile.is_zipfile(path):
                _verify_archive(path)
                file_path = path
                file_name = path.name
            elif path.is_dir():
                temporary_path = _zip_directory(path, root)
                _verify_archive(temporary_path)
                file_path = temporary_path
                file_name = f"audit-pack-{run_id}.zip"
            else:
                raise _export_not_found(export_id, run_id)
        except (
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            UnicodeDecodeError,
            EOFError,
            zlib.error,
            zipfile.BadZipFile,
        ):
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise _export_not_found(export_id, run_id) from None

        return DownloadableAuditPack(
            export_id=export_id,
            run_id=run_id,
            file_name=file_name,
            file_path=file_path,
            delete_after_download=temporary_path is not None,
        )


def _zip_directory(directory: Path, project_root: Path) -> Path:
    """Package legacy directory exports to a temporary archive on disk."""
    package_root = directory.resolve(strict=True)
    package_root.relative_to(project_root)
    fd, name = tempfile.mkstemp(prefix="cardre-audit-pack-", suffix=".zip")
    os.close(fd)
    archive_path = Path(name)
    try:
        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for item in sorted(directory.rglob("*")):
                if item.is_symlink():
                    raise ValueError("Audit pack contains a symlink.")
                if not item.is_file():
                    continue
                resolved = item.resolve(strict=True)
                resolved.relative_to(package_root)
                archive.write(resolved, item.relative_to(directory).as_posix())
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise
    return archive_path


def _verify_archive(path: Path) -> None:
    """Verify archive paths and checksums incrementally from disk."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "checksums.sha256" not in names:
            raise ValueError("Audit pack archive is missing or duplicates required files.")
        for name in names:
            member_path = Path(name)
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or "\\" in name
                or name.endswith("/")
            ):
                raise ValueError("Audit pack archive contains an unsafe path.")

        expected: dict[str, str] = {}
        checksums = archive.read("checksums.sha256").decode("utf-8")
        for line in checksums.splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if match is None:
                raise ValueError("Audit pack checksums are malformed.")
            digest, name = match.groups()
            if name in expected or name == "checksums.sha256":
                raise ValueError("Audit pack checksums contain a duplicate entry.")
            expected[name] = digest

        actual_names = set(names) - {"checksums.sha256"}
        if actual_names != set(expected):
            raise ValueError("Audit pack checksums do not cover every file.")
        for name, expected_digest in expected.items():
            digest = hashlib.sha256()
            with archive.open(name) as member:
                for chunk in iter(lambda: member.read(VERIFY_CHUNK_SIZE), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected_digest:
                raise ValueError("Audit pack checksum verification failed.")


def _export_not_found(export_id: str, run_id: str) -> CardreError:
    return CardreError(
        f"Audit pack {export_id!r} was not found for run {run_id!r}.",
        code=ErrorCode.ARTIFACT_NOT_FOUND,
        context={"export_id": export_id, "run_id": run_id},
    )
