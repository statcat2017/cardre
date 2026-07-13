"""Shared export/report directory listing.

The ``exports/`` directory under a project root contains:
- ``export-{run_id}-{suffix}/`` — export directories
- ``manifest-{run_id}/`` — report directories

This module provides a single function to list them, used by the
exports and reports route handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


@dataclass
class ExportDirInfo:
    """Info about a single export or report directory."""
    name: str
    run_id: str
    path: str
    size_bytes: int = 0


def list_export_dirs(
    store: ProjectStore,
    *,
    prefix: str = "export-",
    run_id: str | None = None,
) -> list[ExportDirInfo]:
    """List export/report directories under ``store.root / exports/``.

    Args:
        store: The project store.
        prefix: Directory name prefix to match (``"export-"`` or ``"manifest-"``).
        run_id: If set, only return directories whose run_id matches.

    Returns:
        Sorted list of ``ExportDirInfo``.
    """
    exports_dir = store.root / "exports"
    if not exports_dir.exists():
        return []

    results: list[ExportDirInfo] = []
    for item in sorted(exports_dir.iterdir()):
        if not item.is_dir() or not item.name.startswith(prefix):
            continue
        parts = item.name.split("-", 2) if prefix == "export-" else item.name.split("-", 1)
        dir_run_id = parts[1] if len(parts) > 1 else ""
        if run_id and dir_run_id != run_id:
            continue
        size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) if prefix == "export-" else 0
        results.append(ExportDirInfo(
            name=item.name,
            run_id=dir_run_id,
            path=str(item),
            size_bytes=size,
        ))
    return results
