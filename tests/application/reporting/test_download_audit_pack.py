from __future__ import annotations

import hashlib
import tracemalloc
import zipfile
from pathlib import Path
from types import SimpleNamespace

from cardre.application.reporting.download_audit_pack import DownloadAuditPack


class _Context:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        return None


class _Factory:
    def __init__(self, uow):
        self.uow = uow

    def read_only(self, project_id):
        return _Context(self.uow)


def _write_large_pack(path: Path, size_bytes: int) -> None:
    digest = hashlib.sha256()
    chunk = bytes(range(256)) * 4096
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        with archive.open("large.bin", "w") as output:
            remaining = size_bytes
            while remaining:
                payload = chunk[: min(len(chunk), remaining)]
                output.write(payload)
                digest.update(payload)
                remaining -= len(payload)
        archive.writestr("checksums.sha256", f"{digest.hexdigest()}  large.bin\n")


def test_download_verifies_large_archive_with_bounded_memory(tmp_path):
    project_root = tmp_path / "project"
    exports_dir = project_root / "exports"
    exports_dir.mkdir(parents=True)
    archive_path = exports_dir / "large-audit-pack.zip"
    _write_large_pack(archive_path, 20 * 1024 * 1024)

    export = SimpleNamespace(
        export_id="export-1",
        export_type="audit_pack",
        path=str(archive_path),
    )
    uow = SimpleNamespace(
        runs=SimpleNamespace(get=lambda run_id: object() if run_id == "run-1" else None),
        exports=SimpleNamespace(list_for_run=lambda run_id: [export]),
    )
    download = DownloadAuditPack(_Factory(uow), lambda project_id: project_root)

    tracemalloc.start()
    try:
        result = download("project-1", "run-1", "export-1")
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result.file_path == archive_path
    assert result.file_name == archive_path.name
    assert result.delete_after_download is False
    assert not hasattr(result, "content")
    assert peak_bytes < 8 * 1024 * 1024
