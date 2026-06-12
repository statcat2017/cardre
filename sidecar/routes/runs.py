"""Run execution endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from sidecar.models import RunRequest, RunResponse, RunStepsResponse, RunStepItem
from sidecar.routes.projects import _load_registry

router = APIRouter(prefix="/runs", tags=["runs"])


def _get_store_for_project(project_id: str):
    registry = _load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})
    from cardre.store import ProjectStore
    return ProjectStore(Path(entry["path"]))


@router.post("", response_model=RunResponse, status_code=201)
def run_plan(body: RunRequest):
    store = _get_store_for_project(body.project_id)

    pv = store.get_plan_version(body.plan_version_id)
    if pv is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_VERSION_NOT_FOUND", "message": "Plan version not found"})

    executor = PlanExecutor(NodeRegistry.with_defaults())
    run_id = None
    try:
        run_id = executor.run_plan_version(store, body.plan_version_id)
    except Exception as exc:
        # run_plan_version may have created the run before the
        # exception. If not, create and finish a failed run.
        if run_id is None:
            run_id = store.create_run(body.plan_version_id)
        store.finish_run(run_id, "failed")
        run = store.get_run(run_id)
        steps = store.get_run_steps(run_id)
        return RunResponse(
            run_id=run["run_id"],
            plan_version_id=run["plan_version_id"],
            status=run["status"],
            started_at=run["started_at"],
            finished_at=run.get("finished_at"),
            step_count=len(steps),
        )

    run = store.get_run(run_id)
    steps = store.get_run_steps(run_id)

    return RunResponse(
        run_id=run["run_id"],
        plan_version_id=run["plan_version_id"],
        status=run["status"],
        started_at=run["started_at"],
        finished_at=run.get("finished_at"),
        step_count=len(steps),
    )


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str):
    registry = _load_registry()
    for pid, entry in registry.items():
        store = _get_store_for_project(pid)
        run = store.get_run(run_id)
        if run is not None:
            steps = store.get_run_steps(run_id)
            return RunResponse(
                run_id=run["run_id"],
                plan_version_id=run["plan_version_id"],
                status=run["status"],
                started_at=run["started_at"],
                finished_at=run.get("finished_at"),
                step_count=len(steps),
            )
    raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id}"})


@router.get("/{run_id}/steps", response_model=RunStepsResponse)
def get_run_steps(run_id: str):
    registry = _load_registry()
    for pid in registry:
        store = _get_store_for_project(pid)
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
                    )
                    for rs in steps
                ],
            )
    raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id}"})
