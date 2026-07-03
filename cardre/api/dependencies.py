"""FastAPI dependency injection for the Cardre v2 API."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from fastapi import Depends, Header, HTTPException

from cardre.api.errors import (
    GOVERNANCE_DISABLED,
    MISSING_PROJECT_ID,
    PROJECT_NOT_FOUND,
    RAW_PROJECT_PATH_DISABLED,
)
from cardre.config import CardreConfig
from cardre.services.project_resolver import ProjectResolver
from cardre.services.run_coordinator import RunCoordinator
from cardre.store.db import ProjectStore


def get_project_store(
    project_id_header: str | None = Header(None, alias="X-Project-Id"),
    project_path: str | None = Header(None, alias="X-Project-Path"),
) -> Generator[ProjectStore, None, None]:
    """Resolve a ``ProjectStore`` from a trusted project id or a dev-only path."""
    config = CardreConfig.from_env()
    resolver = ProjectResolver(config.registry_path)

    if project_id_header:
        root = resolver.resolve_root(project_id_header)
        store = get_project_store_by_root(root)
        try:
            yield store
        finally:
            store.close()
        return

    if project_path:
        if not _raw_project_path_allowed():
            raise HTTPException(
                status_code=400,
                detail={
                    "code": RAW_PROJECT_PATH_DISABLED,
                    "message": (
                        "X-Project-Path is disabled by default. Set CARDRE_ALLOW_RAW_PROJECT_PATH=1 "
                        "for development-only access or send X-Project-Id instead."
                    ),
                },
            )
        root = Path(project_path).resolve()
        if not root.exists():
            raise HTTPException(
                status_code=404,
                detail={
                    "code": PROJECT_NOT_FOUND,
                    "message": f"Project not found at {project_path}.",
                },
            )
        store = get_project_store_by_root(root)
        try:
            yield store
        finally:
            store.close()
        return

    if not project_id_header:
        raise HTTPException(
            status_code=400,
            detail={
                "code": MISSING_PROJECT_ID,
                "message": "X-Project-Id header is required.",
            },
        )

    return


def _raw_project_path_allowed() -> bool:
    return os.environ.get("CARDRE_ALLOW_RAW_PROJECT_PATH", "0").strip().lower() in (
        "1",
        "true",
    )


def get_project_store_by_root(root: Path) -> ProjectStore:
    """Open a fresh store for a given root path."""
    store = ProjectStore(root)
    store.open()
    return store


def require_governance() -> None:
    """Raise ``GOVERNANCE_DISABLED`` (403) if governance is not enabled."""
    config = CardreConfig.from_env()
    if not config.governance_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": GOVERNANCE_DISABLED,
                "message": (
                    "This endpoint requires CARDRE_GOVERNANCE=1. "
                    "Set the environment variable to enable governance features."
                ),
                "context": {},
            },
        )


def get_run_coordinator(
    store: ProjectStore = Depends(get_project_store),
) -> RunCoordinator:
    """Create a ``RunCoordinator`` for the current project store."""
    return RunCoordinator(store)


__all__ = [
    "get_project_store",
    "get_project_store_by_root",
    "get_run_coordinator",
    "require_governance",
]
