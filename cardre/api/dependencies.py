"""FastAPI dependency injection for the Cardre hexagonal architecture."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, Header, Request

from cardre.api.errors import CardreApiError, ErrorCode
from cardre.bootstrap.container import Container


def get_container(request: Request) -> Container:
    """Return the application container from app state."""
    container: Container = request.app.state.container
    return container


def get_uow_factory(container: Container = Depends(get_container)) -> Any:
    return container.uow_factory


def get_settings(container: Container = Depends(get_container)) -> Any:
    return container.settings


def _raw_project_path_allowed() -> bool:
    return os.environ.get("CARDRE_ALLOW_RAW_PROJECT_PATH", "0").strip().lower() in (
        "1",
        "true",
    )


def resolve_project_root(
    project_id: str,
    x_project_id: str | None = Header(None, alias="X-Project-Id"),
    x_project_path: str | None = Header(None, alias="X-Project-Path"),
    container: Container = Depends(get_container),
) -> Path:
    """Resolve the project root for a project-scoped request.

    Precedence: ``X-Project-Id`` (registry lookup) then ``X-Project-Path``
    (dev-only, gated by ``CARDRE_ALLOW_RAW_PROJECT_PATH``). Raises the
    standard error envelope on failure.
    """
    if x_project_id:
        root = container.project_registry.resolve_root(x_project_id)
        if root is None or not root.exists():
            raise CardreApiError(
                code=ErrorCode.PROJECT_NOT_FOUND,
                message=f"Project {x_project_id!r} not found.",
                status_code=404,
            )
        return root
    if x_project_path:
        if not _raw_project_path_allowed():
            raise CardreApiError(
                code=ErrorCode.RAW_PROJECT_PATH_DISABLED,
                message=(
                    "X-Project-Path is disabled by default. Set "
                    "CARDRE_ALLOW_RAW_PROJECT_PATH=1 for development-only "
                    "access or send X-Project-Id instead."
                ),
                status_code=400,
            )
        root = Path(x_project_path).resolve()
        if not root.exists():
            raise CardreApiError(
                code=ErrorCode.PROJECT_NOT_FOUND,
                message=f"Project not found at {x_project_path}.",
                status_code=404,
            )
        return root
    raise CardreApiError(
        code=ErrorCode.MISSING_PROJECT_ID,
        message="X-Project-Id header is required.",
        status_code=400,
    )


def require_governance() -> None:
    """Raise ``GOVERNANCE_DISABLED`` (403) if governance is not enabled.

    Reads ``CardreConfig.from_env()`` at request time so tests can
    monkeypatch it per-test.
    """
    from cardre.config import CardreConfig

    config = CardreConfig.from_env()
    if not config.governance_enabled:
        raise CardreApiError(
            code=ErrorCode.GOVERNANCE_DISABLED,
            message=(
                "This endpoint requires CARDRE_GOVERNANCE=1. "
                "Set the environment variable to enable governance features."
            ),
            status_code=403,
        )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def get_create_project(container: Container = Depends(get_container)) -> Any:
    return container.create_project


def get_list_projects(container: Container = Depends(get_container)) -> Any:
    return container.list_projects


def get_get_project(container: Container = Depends(get_container)) -> Any:
    return container.get_project


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def get_submit_run_factory(container: Container = Depends(get_container)) -> Any:
    return container.submit_run_factory


def get_run_queries(container: Container = Depends(get_container)) -> dict[str, Any]:
    """Return run query helpers that use the UoW directly."""
    uow = container.uow_factory

    def get_run(project_id: str, run_id: str):
        with uow.read_only(project_id) as u:
            return u.runs.get(run_id)

    def list_runs(project_id: str, plan_version_id: str | None = None):
        with uow.read_only(project_id) as u:
            return u.runs.list_for_project(project_id)

    def get_run_steps(project_id: str, run_id: str):
        with uow.read_only(project_id) as u:
            return u.run_steps.get_for_run(run_id)

    return {"get_run": get_run, "list_runs": list_runs, "get_run_steps": get_run_steps}


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def get_explain_staleness(container: Container = Depends(get_container)) -> Any:
    from cardre.application.evidence.explain_staleness import ExplainStaleness

    uow = container.uow_factory

    def factory(project_id: str):
        def f():
            return uow.for_project(project_id)
        return ExplainStaleness(f)

    return factory


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def get_artifact_reader(container: Container = Depends(get_container)) -> Any:
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore

    def factory(project_id: str):
        uow = container.uow_factory
        with uow.read_only(project_id):
            return FsArtifactStore(container.project_registry.resolve_root(project_id))

    return factory


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


def get_governance_use_cases(container: Container = Depends(get_container)) -> dict[str, Any]:
    return {
        "create_branch": lambda pid: container.create_branch_factory(pid),
        "create_comparison": lambda pid: container.create_comparison_factory(pid),
        "assign_champion": lambda pid: container.assign_champion_factory(pid),
        "refresh_comparison": lambda pid: container.refresh_comparison_factory(pid),
    }


def get_governance_enabled(container: Container = Depends(get_container)) -> bool:
    return getattr(container.settings, "governance_enabled", False)


# ---------------------------------------------------------------------------
# Node catalogue
# ---------------------------------------------------------------------------


def get_node_catalogue(container: Container = Depends(get_container)) -> Any:
    return container.node_catalogue


# ---------------------------------------------------------------------------
# Reports / exports
# ---------------------------------------------------------------------------


def get_generate_report(container: Container = Depends(get_container)) -> Any:
    return container.generate_report


def get_export_audit_pack(container: Container = Depends(get_container)) -> Any:
    return container.export_audit_pack
