"""Project-scoped filesystem storage for imported Parquet datasets."""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import IO, BinaryIO

import polars as pl

from cardre.application.datasets.constants import MAX_DATASET_BYTES
from cardre.application.ports.dataset_store import ImportedDataset
from cardre.domain.errors import CardreError, ErrorCode

_SOURCE_REF = re.compile(r"dataset:([0-9a-f]{32})")


class FsDatasetStore:
    """Keep uploaded files below ``<project-root>/datasets``.

    Client filenames are retained only as display metadata in the response.
    They never participate in a filesystem path.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()

    def import_parquet(self, source: BinaryIO, file_name: str) -> ImportedDataset:
        display_name = _display_filename(file_name)
        if not display_name.lower().endswith(".parquet"):
            raise _invalid_dataset("Choose a Parquet file with a .parquet extension.")

        dataset_dir = self._dataset_dir(create=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b", prefix=".upload-", suffix=".tmp", dir=dataset_dir, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                size_bytes = _copy_limited(source, temporary.file)
                temporary.flush()
                os.fsync(temporary.fileno())

            _validate_parquet(temporary_path)
            dataset_id = uuid.uuid4().hex
            destination = dataset_dir / f"{dataset_id}.parquet"
            os.replace(temporary_path, destination)
            temporary_path = None
            return ImportedDataset(
                source_ref=f"dataset:{dataset_id}",
                file_name=display_name,
                size_bytes=size_bytes,
            )
        except CardreError:
            raise
        except OSError as exc:
            raise CardreError(
                "The selected dataset could not be saved in this Project.",
                code=ErrorCode.DATASET_STORAGE_FAILED,
                context={},
                status_code=500,
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def resolve_source(self, source_ref: str) -> Path:
        match = _SOURCE_REF.fullmatch(source_ref)
        if match is None:
            raise _dataset_not_found()

        dataset_dir = self._dataset_dir(create=False)
        candidate = dataset_dir / f"{match.group(1)}.parquet"
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise _dataset_not_found() from exc

        if candidate.is_symlink() or not resolved.is_relative_to(dataset_dir.resolve()):
            raise _dataset_not_found()
        if not resolved.is_file():
            raise _dataset_not_found()
        return resolved

    def _dataset_dir(self, *, create: bool) -> Path:
        dataset_dir = self._root / "datasets"
        if create:
            dataset_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if dataset_dir.is_symlink():
            raise CardreError(
                "The Project dataset directory is not a safe local directory.",
                code=ErrorCode.DATASET_STORAGE_FAILED,
                context={},
                status_code=500,
            )
        try:
            resolved = dataset_dir.resolve(strict=create)
        except OSError as exc:
            raise CardreError(
                "The Project dataset directory is unavailable.",
                code=ErrorCode.DATASET_STORAGE_FAILED,
                context={},
                status_code=500,
            ) from exc
        if not resolved.is_relative_to(self._root) or resolved == self._root:
            raise CardreError(
                "The Project dataset directory is not a safe local directory.",
                code=ErrorCode.DATASET_STORAGE_FAILED,
                context={},
                status_code=500,
            )
        return resolved


def _display_filename(file_name: str) -> str:
    display_name = file_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
    display_name = "".join(character for character in display_name if character >= " " and character != "\x7f")
    if not display_name or len(display_name) > 255:
        raise _invalid_dataset("The selected file must have a valid filename.")
    return display_name


def _copy_limited(source: BinaryIO, destination: IO[bytes]) -> int:
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_DATASET_BYTES:
            raise CardreError(
                "The selected dataset exceeds the 1 GiB upload limit.",
                code=ErrorCode.UPLOAD_TOO_LARGE,
                context={"max_bytes": MAX_DATASET_BYTES},
                status_code=413,
            )
        destination.write(chunk)
    if size == 0:
        raise _invalid_dataset("The selected Parquet file is empty.")
    return size


def _validate_parquet(path: Path) -> None:
    try:
        with path.open("rb") as source:
            header = source.read(4)
            source.seek(-4, os.SEEK_END)
            footer = source.read(4)
        if header != b"PAR1" or footer != b"PAR1":
            raise ValueError("missing Parquet magic bytes")
        if not pl.read_parquet_schema(path):
            raise ValueError("the Parquet file has no columns")
    except Exception as exc:
        raise _invalid_dataset(
            "The selected file is not a readable Parquet dataset. Choose another .parquet file."
        ) from exc


def _invalid_dataset(message: str) -> CardreError:
    return CardreError(
        message,
        code=ErrorCode.DATASET_INVALID,
        context={},
        status_code=422,
    )


def _dataset_not_found() -> CardreError:
    return CardreError(
        "The selected dataset is not available in this Project.",
        code=ErrorCode.DATASET_NOT_FOUND,
        context={},
        status_code=404,
    )
