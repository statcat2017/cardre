"""FastAPI dependency injection for the Cardre hexagonal architecture."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from cardre.bootstrap.container import Container


def get_container(request: Request) -> Container:
    """Return the application container from app state."""
    container: Container = request.app.state.container
    return container


def get_uow_factory(container: Container = Depends(get_container)) -> Any:
    return container.uow_factory


def get_settings(container: Container = Depends(get_container)) -> Any:
    return container.settings


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
    from cardre.application.governance.assign_champion import AssignChampion
    from cardre.application.governance.create_branch import CreateBranch
    from cardre.application.governance.create_comparison import CreateComparison

    uow = container.uow_factory

    return {
        "create_branch": lambda pid: CreateBranch(lambda: uow.for_project(pid)),
        "create_comparison": lambda pid: CreateComparison(lambda: uow.for_project(pid)),
        "assign_champion": lambda pid: AssignChampion(lambda: uow.for_project(pid)),
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
