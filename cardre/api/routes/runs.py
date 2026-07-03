"""Run endpoints — create, list, inspect runs and run steps."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store, get_run_coordinator
from cardre.api.errors import PLAN_VERSION_NOT_FOUND, RUN_NOT_FOUND, CardreApiError
from cardre.api.routes._project_scope import plan_version_belongs_to_project, run_belongs_to_project
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
            RunResponse(
                run_id=r["run_id"],
                plan_version_id=r["plan_version_id"],
                status=r["status"],
                started_at=r["started_at"],
                finished_at=r.get("finished_at"),
                branch_id=r.get("branch_id"),
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
    return RunResponse(
        run_id=summary.run_id,
        plan_version_id=summary.plan_version_id,
        status=summary.status,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        step_count=summary.step_count,
        branch_id=summary.branch_id,
        executed_step_ids=summary.executed_step_ids or [],
        diagnostics=summary.diagnostics or [],
        latest_error=summary.latest_error,
        heartbeat_at=summary.heartbeat_at,
        is_stale=summary.is_stale,
    )


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
    return RunResponse(
        run_id=summary.run_id,
        plan_version_id=summary.plan_version_id,
        status=summary.status,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        step_count=summary.step_count,
        branch_id=summary.branch_id,
        executed_step_ids=summary.executed_step_ids or [],
        diagnostics=summary.diagnostics or [],
        latest_error=summary.latest_error,
        heartbeat_at=summary.heartbeat_at,
        is_stale=summary.is_stale,
    )


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
    return [
        RunStepResponse(
            run_step_id=rs.run_step_id,
            run_id=rs.run_id,
            step_id=rs.step_id,
            plan_version_id=rs.plan_version_id,
            status=rs.status.value,
            started_at=rs.started_at,
            finished_at=rs.finished_at,
            execution_fingerprint=rs.execution_fingerprint,
            warnings=rs.warnings,
            errors=rs.errors,
        )
        for rs in steps
    ]


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
    from cardre.store.run_step_repo import RunStepRepository
    rs_repo = RunStepRepository(store)
    steps = rs_repo.get_for_run(run_id)
    all_edges = []
    for rs in steps:
        edges = evidence_repo.get_edges_for_run_step(rs.run_step_id)
        for edge in edges:
            artifacts = evidence_repo.get_artifacts_for_edge(edge.evidence_edge_id)
            all_edges.append(
                RunEvidenceEdgeResponse(
                    evidence_edge_id=edge.evidence_edge_id,
                    run_id=edge.run_id,
                    run_step_id=edge.run_step_id,
                    plan_version_id=edge.plan_version_id,
                    step_id=edge.step_id,
                    parent_step_id=edge.parent_step_id,
                    source_run_id=edge.source_run_id,
                    source_run_step_id=edge.source_run_step_id,
                    policy=edge.policy,
                    source_label=edge.source_label,
                    is_reused=edge.is_reused,
                    is_stale=edge.is_stale,
                    stale_reason=edge.stale_reason,
                    created_at=getattr(edge, "created_at", ""),
                    artifacts=[
                        {
                            "evidence_artifact_id": a.evidence_artifact_id,
                            "evidence_edge_id": edge.evidence_edge_id,
                            "artifact_id": a.artifact_id,
                            "role": a.role,
                        }
                        for a in artifacts
                    ],
                )
            )
    return all_edges
