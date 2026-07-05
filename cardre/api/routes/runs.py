"""Run endpoints — create, list, inspect runs and run steps."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, get_run_coordinator
from cardre.api.errors import PLAN_VERSION_NOT_FOUND, RUN_NOT_FOUND, CardreApiError
from cardre.api.routes._project_scope import plan_version_belongs_to_project, run_belongs_to_project
from cardre.api.routes._run_mappings import (
    evidence_edge_to_response,
    run_step_to_response,
    run_summary_to_response,
)
from cardre.api.schemas import (
    RunCreateRequest,
    RunEvidenceEdgeResponse,
    RunListResponse,
    RunResponse,
    RunStepResponse,
)
from cardre.domain.evidence import EvidenceArtifact
from cardre.services.run_coordinator import RunCoordinator, RunSummary
from cardre.store.db import ProjectStore
from cardre.store.evidence_repo import EvidenceRepository
from cardre.store.run_repo import RunRepository
from cardre.store.run_step_repo import RunStepRepository

router = APIRouter(prefix="/projects/{project_id}", tags=["runs"])


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> RunListResponse:
    """List all runs for a project."""
    repo = RunRepository(store)
    runs = repo.list_for_project(project_id)
    return RunListResponse(
        runs=[
            run_summary_to_response(
                RunSummary(
                    run_id=r["run_id"],
                    plan_version_id=r["plan_version_id"],
                    status=r["status"],
                    started_at=r["started_at"],
                    finished_at=r.get("finished_at"),
                    branch_id=r.get("branch_id"),
                )
            )
            for r in runs
        ]
    )


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    project_id: str,
    run_id: str,
    store: ProjectStore = Depends(get_project_store),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> RunResponse:
    """Get a single run by ID with summary info."""
    if not run_belongs_to_project(store, project_id, run_id):
        raise CardreApiError(
            code=RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    summary = coordinator.get_summary(run_id)
    return run_summary_to_response(summary)


@router.post("/runs", response_model=RunResponse, status_code=201)
async def create_run(
    project_id: str,
    body: RunCreateRequest,
    store: ProjectStore = Depends(get_project_store),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> RunResponse:
    """Create and optionally execute a run for a plan version."""
    if not plan_version_belongs_to_project(store, project_id, body.plan_version_id):
        raise CardreApiError(
            code=PLAN_VERSION_NOT_FOUND,
            message=f"Plan version {body.plan_version_id!r} not found.",
            status_code=404,
        )
    summary = coordinator.run(body.plan_version_id, sync=body.sync, force=body.force)
    return run_summary_to_response(summary)


@router.get("/runs/{run_id}/steps", response_model=list[RunStepResponse])
async def list_run_steps(
    project_id: str,
    run_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> list[RunStepResponse]:
    """List all steps for a run."""
    if not run_belongs_to_project(store, project_id, run_id):
        raise CardreApiError(
            code=RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    rs_repo = RunStepRepository(store)
    steps = rs_repo.get_for_run(run_id)
    return [run_step_to_response(rs) for rs in steps]


@router.get("/runs/{run_id}/evidence", response_model=list[RunEvidenceEdgeResponse])
async def list_run_evidence(
    project_id: str,
    run_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> list[RunEvidenceEdgeResponse]:
    """List all evidence edges for a run."""
    if not run_belongs_to_project(store, project_id, run_id):
        raise CardreApiError(
            code=RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    evidence_repo = EvidenceRepository(store)
    edges = evidence_repo.get_edges_for_run(run_id)
    artifacts_by_edge_id: dict[str, list[EvidenceArtifact]] = {}
    for artifact in evidence_repo.get_artifacts_for_run(run_id):
        artifacts_by_edge_id.setdefault(artifact.evidence_edge_id, []).append(artifact)
    return [
        evidence_edge_to_response(edge, artifacts_by_edge_id.get(edge.evidence_edge_id, []))
        for edge in edges
    ]
