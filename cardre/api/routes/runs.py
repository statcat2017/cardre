"""Run endpoints — create, list, inspect runs and run steps."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, get_run_coordinator
from cardre.api.errors import CardreApiError, ErrorCode
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
from cardre.services.run_coordinator import RunCoordinator
from cardre.store.db import ProjectStore
from cardre.store.evidence_repo import EvidenceRepository
from cardre.store.run_step_repo import RunStepRepository

router = APIRouter(prefix="/projects/{project_id}", tags=["runs"])


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
    coordinator: RunCoordinator = Depends(get_run_coordinator),
) -> RunListResponse:
    """List all runs for a project."""
    summaries = coordinator.list_for_project(project_id)
    return RunListResponse(
        runs=[run_summary_to_response(s) for s in summaries]
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
            code=ErrorCode.RUN_NOT_FOUND,
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
            code=ErrorCode.PLAN_VERSION_NOT_FOUND,
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
            code=ErrorCode.RUN_NOT_FOUND,
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
            code=ErrorCode.RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    evidence_repo = EvidenceRepository(store)
    return [
        evidence_edge_to_response(edge, arts)
        for edge, arts in evidence_repo.list_for_run_ordered(run_id)
    ]
