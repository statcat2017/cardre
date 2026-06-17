"""Shared FastAPI dependencies for the Cardre sidecar.

Consolidates store resolution so route handlers don't repeat the
registry-lookup + HTTPException pattern.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from cardre.services.project_registry import (
    ProjectNotFoundError,
    ProjectPathMissingError,
    get_store_for_project,
    load_registry,
)
from cardre.store import ProjectStore


def resolve_project_store(project_id: str) -> ProjectStore:
    """Look up a project's store by ID, raising HTTPException on failure."""
    try:
        return get_store_for_project(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": str(exc)})
    except ProjectPathMissingError as exc:
        raise HTTPException(status_code=410, detail={"code": "PROJECT_PATH_MISSING", "message": str(exc)})


def resolve_registry_entry(project_id: str) -> dict:
    """Look up a registry entry by project ID, raising HTTPException on failure."""
    registry = load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})
    return entry


def project_store_from_registry(project_id: str) -> ProjectStore:
    """Build a ProjectStore from a registry entry (skips SQLite path check)."""
    entry = resolve_registry_entry(project_id)
    from cardre.store import ProjectStore
    return ProjectStore(Path(entry["path"]))
