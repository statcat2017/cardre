"""Run execution endpoints — async execution with polling."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.services.project_registry import get_store_for_project, load_registry, ProjectNotFoundError, ProjectPathMissingError
from cardre.store import ProjectStore
from sidecar.models import RunRequest, RunResponse, RunStepsResponse, RunStepItem

router = APIRouter(prefix="/runs", tags=["runs"])


def _run_background(project_path: str, plan_version_id: str, run_id: str) -> None:
    """Execute plan steps in a background thread."""
    store = ProjectStore(project_path)
    executor = PlanExecutor(NodeRegistry.with_defaults())
    try:
        executor.run_plan_version(store, plan_version_id, run_id=run_id)
    except BaseException:
        store.finish_run(run_id, "failed")


def _branch_run_background(project_path: str, plan_version_id: str, branch_id: str, run_id: str) -> None:
    """Execute branch-owned steps in a background thread."""
    store = ProjectStore(project_path)
    executor = PlanExecutor(NodeRegistry.with_defaults())
    try:
        executor.run_branch(store, plan_version_id, branch_id, run_id=run_id)
    except BaseException:
        store.finish_run(run_id, "failed")


def _build_run_response(store: ProjectStore, run_id: str, executed_ids: list[str] | None = None) -> RunResponse:
    run = store.get_run(run_id)
    steps = store.get_run_steps(run_id)
    return RunResponse(
        run_id=run["run_id"],
        plan_version_id=run["plan_version_id"],
        status=run["status"],
        started_at=run["started_at"],
        finished_at=run.get("finished_at"),
        step_count=len(steps),
        branch_id=run.get("branch_id"),
        executed_step_ids=executed_ids or [],
    )


@router.post("", response_model=RunResponse, status_code=201)
def run_plan(body: RunRequest, sync: bool = Query(default=False, description="Execute synchronously (for tests)")):
    store = get_store_for_project(body.project_id)

    pv = store.get_plan_version(body.plan_version_id)
    if pv is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_VERSION_NOT_FOUND", "message": "Plan version not found"})

    executor = PlanExecutor(NodeRegistry.with_defaults())

    if body.run_scope == "branch" and body.branch_id:
        if sync:
            try:
                run_id = executor.run_branch(store, body.plan_version_id, body.branch_id)
                executed_ids = [rs.step_id for rs in store.get_run_steps(run_id)]
                return _build_run_response(store, run_id, executed_ids)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "BRANCH_RUN_FAILED", "message": str(exc)})
        run_id = store.create_run(body.plan_version_id, branch_id=body.branch_id)
        entry = load_registry().get(body.project_id)
        if entry:
            t = threading.Thread(target=_branch_run_background, args=(entry["path"], body.plan_version_id, body.branch_id, run_id))
            t.start()
        return _build_run_response(store, run_id)

    if sync:
        try:
            run_id = executor.run_plan_version(store, body.plan_version_id)
        except Exception as exc:
            run_id = store.create_run(body.plan_version_id)
            store.finish_run(run_id, "failed")
            return _build_run_response(store, run_id)
        return _build_run_response(store, run_id)

    # Async (default): create run immediately, execute in background
    run_id = store.create_run(body.plan_version_id)
    entry = load_registry().get(body.project_id)
    if entry:
        t = threading.Thread(target=_run_background, args=(entry["path"], body.plan_version_id, run_id))
        t.start()
    return _build_run_response(store, run_id)


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str):
    registry = load_registry()
    for pid, entry in registry.items():
        try:
            store = get_store_for_project(pid)
        except (ProjectNotFoundError, ProjectPathMissingError):
            continue
        run = store.get_run(run_id)
        if run is not None:
            return _build_run_response(store, run_id)
    raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id}"})


@router.get("/{run_id}/steps", response_model=RunStepsResponse)
def get_run_steps(run_id: str):
    registry = load_registry()
    for pid in registry:
        try:
            store = get_store_for_project(pid)
        except (ProjectNotFoundError, ProjectPathMissingError):
            continue
        run = store.get_run(run_id)
        if run is not None:
            steps = store.get_run_steps(run_id)
            return RunStepsResponse(
                run_id=run_id,
                steps=[
                    RunStepItem(
                        run_step_id=rs.run_step_id,
                        step_id=rs.step_id,
                        node_type=rs.execution_fingerprint.get("node_type", ""),
                        status=rs.status,
                        started_at=rs.started_at,
                        finished_at=rs.finished_at,
                        input_artifact_ids=rs.input_artifact_ids,
                        output_artifact_ids=rs.output_artifact_ids,
                        warnings=rs.warnings,
                        errors=rs.errors,
                        is_carried_forward=rs.execution_fingerprint.get("cardre_step_carried_forward", False),
                    )
                    for rs in steps
                ],
            )
    raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id}"})
