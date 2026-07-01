"""FastAPI dependency injection for the Cardre v2 API."""

from __future__ import annotations

from pathlib import Path

from fastapi import Header, HTTPException

from cardre.store.db import ProjectStore


# In-memory cache of open ProjectStore instances per project root.
_open_stores: dict[str, ProjectStore] = {}


def get_project_store(
    project_path: str | None = Header(None, alias="X-Project-Path"),
) -> ProjectStore:
    """Resolve a ``ProjectStore`` from the ``X-Project-Path`` header.

    In a real deployment the store would be resolved from the project
    registry; for the minimal Phase 2 API we accept a path header.
    """
    if not project_path:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_PROJECT_PATH",
                "message": "X-Project-Path header is required.",
            },
        )

    root = Path(project_path).resolve()
    if not root.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PROJECT_NOT_FOUND",
                "message": f"Project not found at {project_path}.",
            },
        )

    key = str(root)
    if key not in _open_stores:
        store = ProjectStore(root)
        store.open()
        _open_stores[key] = store

    return _open_stores[key]


def get_project_store_by_root(root: Path) -> ProjectStore:
    """Open or retrieve a cached store for a given root path."""
    key = str(root.resolve())
    if key not in _open_stores:
        store = ProjectStore(root)
        store.open()
        _open_stores[key] = store
    return _open_stores[key]


__all__ = [
    "get_project_store",
    "get_project_store_by_root",
]
