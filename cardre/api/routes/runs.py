"""Run endpoints — create, list, inspect runs and run steps."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.mappers import evidence_edge_to_response, run_step_to_response, run_to_response
from cardre.api.schemas import (
    RunCreateRequest,
    RunEvidenceEdgeResponse,
    RunListResponse,
    RunResponse,
    RunStepResponse,
)
from cardre.bootstrap.container import Container
from cardre.domain.run import RunStatus

router = APIRouter(prefix="/projects/{project_id}", tags=["runs"])

_STALE_SECONDS = 300


def _enrich_run(container: Container, project_id: str, run_id: str, *, cancel_requested: bool = False) -> RunResponse:
    """Build a truthful RunResponse with steps, diagnostics, and staleness."""
    from datetime import UTC, datetime

    from cardre.domain.errors import CardreError

    try:
        with container.uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
            if run is None:
                raise CardreApiError(
                    code=ErrorCode.RUN_NOT_FOUND,
                    message=f"Run {run_id!r} not found.",
                    status_code=404,
                )
            steps = uow.run_steps.get_for_run(run_id)
            diagnostics = uow.runs.get_diagnostics(run_id)
    except CardreError as exc:
        if exc.code == "PROJECT_NOT_FOUND":
            raise CardreApiError(
                code=ErrorCode.PROJECT_NOT_FOUND,
                message=str(exc),
                status_code=404,
            ) from exc
        raise

    executed = [s.step_id for s in steps if s.status.value == "succeeded"]
    is_stale = False
    hb: str | None = None
    try:
        with container.uow_factory.read_only(project_id) as uow:
            row = uow.runs.get(run_id)
    except Exception:
        row = None
    if row is not None:
        hb = getattr(row, "heartbeat_at", None)
    if run.status == RunStatus.RUNNING and hb is None:
        is_stale = True
    elif hb is not None:
        try:
            hb_ts = datetime.fromisoformat(hb).replace(tzinfo=UTC).timestamp()
            now_ts = datetime.now(UTC).timestamp()
            is_stale = (now_ts - hb_ts) > _STALE_SECONDS and run.status == RunStatus.RUNNING
        except (ValueError, TypeError):
            is_stale = run.status == RunStatus.RUNNING

    return run_to_response(
        run,
        step_count=len(steps),
        executed_step_ids=executed,
        diagnostics=diagnostics,
        heartbeat_at=hb,
        is_stale=is_stale,
        cancel_requested=cancel_requested,
    )


@router.post("/runs", response_model=RunResponse, status_code=201)
async def create_run(project_id: str, body: RunCreateRequest, container=Depends(get_container)):
    from cardre.application.runs.submit_run import SubmitRunCommand
    from cardre.domain.errors import CardreError

    submit = container.submit_run_factory(project_id)
    try:
        result = submit(SubmitRunCommand(
            plan_version_id=body.plan_version_id,
            run_scope=body.run_scope,
            branch_id=body.branch_id,
            force=body.force,
            sync=body.sync,
        ))
    except CardreError as exc:
        if exc.code == "PLAN_VERSION_NOT_FOUND" or "not found" in (exc.message or "").lower():
            raise CardreApiError(
                code=ErrorCode.PLAN_VERSION_NOT_FOUND,
                message=str(exc),
                status_code=404,
            ) from exc
        if "concurrent run" in (exc.message or "").lower():
            raise CardreApiError(
                code=ErrorCode.CONCURRENT_RUN,
                message=str(exc),
                status_code=409,
            ) from exc
        raise
    return _enrich_run(container, project_id, result.run_id)


@router.get("/runs", response_model=RunListResponse)
async def list_runs(project_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        runs = uow.runs.list_for_project(project_id)
    return RunListResponse(runs=[_enrich_run(container, project_id, r.run_id) for r in runs])


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(project_id: str, run_id: str, container=Depends(get_container)):
    return _enrich_run(container, project_id, run_id)


@router.get("/runs/{run_id}/steps", response_model=list[RunStepResponse])
async def get_run_steps(project_id: str, run_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        steps = uow.run_steps.get_for_run(run_id)
    return [run_step_to_response(s) for s in steps]


@router.get("/runs/{run_id}/evidence", response_model=list[RunEvidenceEdgeResponse])
async def get_run_evidence(project_id: str, run_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        edges = uow.evidence.get_edges_for_run(run_id)
        result = []
        for edge in edges:
            artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
            result.append(evidence_edge_to_response(edge, artifacts))
    return result


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(project_id: str, run_id: str, container=Depends(get_container)):
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    from cardre.domain.errors import CardreError

    def factory():
        return container.uow_factory.for_project(project_id)

    try:
        CancelRun(factory)(CancelRunCommand(run_id=run_id))
    except CardreError as exc:
        if exc.code == "RUN_NOT_FOUND":
            raise CardreApiError(
                code=ErrorCode.RUN_NOT_FOUND,
                message=str(exc),
                status_code=404,
            ) from exc
        if exc.code == "RUN_NOT_RUNNING":
            raise CardreApiError(
                code=ErrorCode.RUN_NOT_RUNNING,
                message=str(exc),
                status_code=409,
            ) from exc
        raise
    return _enrich_run(container, project_id, run_id, cancel_requested=True)
