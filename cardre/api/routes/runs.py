"""Run endpoints — create, list, inspect runs and run steps."""

from __future__ import annotations

from typing import Any

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

router = APIRouter(prefix="/projects/{project_id}", tags=["runs"])


def _load_run(container: Container, project_id: str, run_id: str) -> RunResponse:
    """Hydrate a truthful RunResponse from persisted run state in one UoW."""
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
    executed = [s.step_id for s in steps if s.status.value == "succeeded"]
    return run_to_response(
        run,
        step_count=len(steps),
        executed_step_ids=executed,
        diagnostics=diagnostics,
        stale_heartbeat_seconds=container.settings.stale_heartbeat_seconds,
    )


@router.post("/runs", response_model=RunResponse, status_code=201)
def create_run(project_id: str, body: RunCreateRequest, container=Depends(get_container)):
    from cardre.application.runs.submit_run import SubmitRunCommand

    submit = container.submit_run_factory(project_id)
    result = submit(SubmitRunCommand(
        plan_version_id=body.plan_version_id,
        run_scope=body.run_scope or "full_plan",
        force=body.force,
        sync=body.sync,
    ))
    return _load_run(container, project_id, result.run_id)


@router.get("/runs", response_model=RunListResponse)
def list_runs(project_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        runs = uow.runs.list_for_project(project_id)
        steps = uow.run_steps.get_for_project(project_id)
        diags = uow.runs.get_diagnostics_for_project(project_id)
    steps_by_run: dict[str, list[Any]] = {}
    for s in steps:
        steps_by_run.setdefault(s.run_id, []).append(s)
    diags_by_run: dict[str, list[dict[str, Any]]] = {}
    for d in diags:
        diags_by_run.setdefault(d["run_id"], []).append(d)
    return RunListResponse(runs=[
        run_to_response(
            r,
            step_count=len(steps_by_run.get(r.run_id, [])),
            executed_step_ids=[s.step_id for s in steps_by_run.get(r.run_id, [])
                               if s.status.value == "succeeded"],
            diagnostics=diags_by_run.get(r.run_id, []),
            stale_heartbeat_seconds=container.settings.stale_heartbeat_seconds,
        )
        for r in runs
    ])


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(project_id: str, run_id: str, container=Depends(get_container)):
    return _load_run(container, project_id, run_id)


@router.get("/runs/{run_id}/steps", response_model=list[RunStepResponse])
def get_run_steps(project_id: str, run_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        if uow.runs.get(run_id) is None:
            raise CardreApiError(
                code=ErrorCode.RUN_NOT_FOUND,
                message=f"Run {run_id!r} not found.",
                status_code=404,
            )
        steps = uow.run_steps.get_for_run(run_id)
    return [run_step_to_response(s) for s in steps]


@router.get("/runs/{run_id}/evidence", response_model=list[RunEvidenceEdgeResponse])
def get_run_evidence(project_id: str, run_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        if uow.runs.get(run_id) is None:
            raise CardreApiError(
                code=ErrorCode.RUN_NOT_FOUND,
                message=f"Run {run_id!r} not found.",
                status_code=404,
            )
        edges = uow.evidence.get_edges_for_run(run_id)
        result = []
        for edge in edges:
            artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
            result.append(evidence_edge_to_response(edge, artifacts))
    return result


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
def cancel_run(project_id: str, run_id: str, container=Depends(get_container)):
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand

    def factory():
        return container.uow_factory.for_project(project_id)

    CancelRun(factory)(CancelRunCommand(run_id=run_id))
    return _load_run(container, project_id, run_id)
