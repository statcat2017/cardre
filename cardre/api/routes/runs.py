"""Run endpoints — create, list, inspect runs and run steps."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.mappers import evidence_edge_to_response, run_step_to_response, run_to_response
from cardre.api.schemas import (
    RunCreateRequest,
    RunEvidenceEdgeResponse,
    RunListResponse,
    RunResponse,
    RunStepResponse,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["runs"])


@router.post("/runs", response_model=RunResponse, status_code=201)
async def create_run(project_id: str, body: RunCreateRequest, container=Depends(get_container)):
    from cardre.application.runs.submit_run import SubmitRunCommand

    submit = container.submit_run_factory(project_id)
    result = submit(SubmitRunCommand(plan_version_id=body.plan_version_id, sync=body.sync))
    with container.uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(result.run_id)
    if run is None:
        from cardre.api.errors import CardreApiError, ErrorCode
        raise CardreApiError(code=ErrorCode.RUN_NOT_FOUND, message="Run not found after creation.", status_code=500)
    return run_to_response(run)


@router.get("/runs", response_model=RunListResponse)
async def list_runs(project_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        runs = uow.runs.list_for_project(project_id)
    return RunListResponse(runs=[run_to_response(r) for r in runs])


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(project_id: str, run_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    if run is None:
        from cardre.api.errors import CardreApiError, ErrorCode
        raise CardreApiError(code=ErrorCode.RUN_NOT_FOUND, message=f"Run {run_id!r} not found.", status_code=404)
    return run_to_response(run)


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

    def factory():
        return container.uow_factory.for_project(project_id)

    CancelRun(factory)(CancelRunCommand(run_id=run_id))
    with container.uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    if run is None:
        from cardre.api.errors import CardreApiError, ErrorCode
        raise CardreApiError(code=ErrorCode.RUN_NOT_FOUND, message=f"Run {run_id!r} not found.", status_code=404)
    return run_to_response(run)
