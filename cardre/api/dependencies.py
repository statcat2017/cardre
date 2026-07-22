"""FastAPI dependency injection for the Cardre hexagonal architecture."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from cardre.bootstrap.container import Container


def get_container(request: Request) -> Container:
    """Return the application container from app state."""
    container: Container = request.app.state.container
    return container


def get_create_project(container: Container = Depends(get_container)) -> Any:
    return container.create_project


def get_list_projects(container: Container = Depends(get_container)) -> Any:
    return container.list_projects


def get_get_project(container: Container = Depends(get_container)) -> Any:
    return container.get_project


# ---------------------------------------------------------------------------
# Legacy stubs — kept for backward compatibility during migration.
# Old route files import these; they are not registered in the new app.
# ---------------------------------------------------------------------------


def get_project_store(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("get_project_store removed; use use-case deps")


def get_project_store_by_root(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("get_project_store_by_root removed; use use-case deps")


def get_run_coordinator(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("get_run_coordinator removed; use use-case deps")


def require_governance(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("require_governance removed; use use-case deps")
