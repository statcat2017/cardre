"""Run execution endpoints — async execution with polling."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.services.project_registry import get_store_for_project, load_registry, ProjectNotFoundError, ProjectPathMissingError
from cardre.store import ProjectStore
from sidecar.models import RunRequest, RunResponse, RunStepsResponse, RunStepItem, ArtifactResponse

router = APIRouter(prefix="/runs", tags=["runs"])


def _fail_run_if_running(store: ProjectStore, run_id: str) -> None:
    """Finish *run_id* as failed, but only if it is still in ``running``
    state (avoid overwriting a finish already written by the executor)."""
    try:
        run = store.get_run(run_id)
        if run and run.get("status") == "running":
            store.finish_run(run_id, "failed")
    except Exception:
        pass


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


def _dispatch_run(
    *,
    project_path: str,
    plan_version_id: str,
    run_id: str,
    force: bool = False,
    run_scope: str = "full",
    branch_id: str | None = None,
    target_step_id: str | None = None,
) -> None:
    """Execute a run in a background thread.  Dispatches to the correct
    executor method based on *run_scope*."""
    store = ProjectStore(project_path)
    executor = PlanExecutor(NodeRegistry.with_defaults())
    try:
        if run_scope == "branch" and branch_id:
            result_id = executor.run_branch(store, plan_version_id, branch_id, run_id=run_id, force=force)
            if result_id != run_id:
                store.finish_run(run_id, "cancelled")
        elif run_scope == "to_node" and target_step_id:
            executor.run_to_node(store, plan_version_id, target_step_id, run_id=run_id, force=force)
        else:
            executor.run_plan_version(store, plan_version_id, run_id=run_id, force=force)
    except BaseException:
        import traceback
        print(f"[sidecar] _dispatch_run({run_id}) failed: {traceback.format_exc()}", flush=True)
        _fail_run_if_running(store, run_id)


@router.post("", response_model=RunResponse, status_code=201)
def run_plan(body: RunRequest, sync: bool = Query(default=False, description="Execute synchronously (for tests)")):
    store = get_store_for_project(body.project_id)

    pv = store.get_plan_version(body.plan_version_id)
    if pv is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_VERSION_NOT_FOUND", "message": "Plan version not found"})

    executor = PlanExecutor(NodeRegistry.with_defaults())

    # Validate scope-specific requirements
    if body.run_scope == "to_node" and not body.target_step_id:
        raise HTTPException(status_code=400, detail={"code": "TARGET_STEP_REQUIRED", "message": "target_step_id is required for to_node scope"})

    # Synchronous execution path
    if sync:
        try:
            if body.run_scope == "to_node":
                run_id = executor.run_to_node(store, body.plan_version_id, body.target_step_id, force=body.force)
            elif body.run_scope == "branch" and body.branch_id:
                run_id = executor.run_branch(store, body.plan_version_id, body.branch_id, force=body.force)
            else:
                run_id = executor.run_plan_version(store, body.plan_version_id, force=body.force)
            executed_ids = [rs.step_id for rs in store.get_run_steps(run_id)]
            return _build_run_response(store, run_id, executed_ids)
        except ValueError as exc:
            scope_label = body.run_scope or "full"
            detail_code = f"{scope_label.upper()}_RUN_FAILED"
            raise HTTPException(status_code=400, detail={"code": detail_code, "message": str(exc)})
        except Exception:
            # Unexpected sync failure: create a failed run so the client
            # can still poll for status rather than getting a 500.
            run_id = store.create_run(body.plan_version_id)
            store.finish_run(run_id, "failed")
            return _build_run_response(store, run_id)

    # Async (default): create run immediately, execute in background
    branch_kw = {"branch_id": body.branch_id} if body.branch_id else {}
    run_id = store.create_run(body.plan_version_id, **branch_kw)
    project_path = str(store.root)
    try:
        t = threading.Thread(
            target=_dispatch_run,
            kwargs={
                "project_path": project_path,
                "plan_version_id": body.plan_version_id,
                "run_id": run_id,
                "force": body.force,
                "run_scope": body.run_scope or "full",
                "branch_id": body.branch_id,
                "target_step_id": body.target_step_id,
            },
            name="run-bg",
        )
        t.start()
    except Exception:
        store.finish_run(run_id, "failed")
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
                        is_carried_forward=rs.is_carried_forward or rs.execution_fingerprint.get("cardre_step_carried_forward", False),
                    )
                    for rs in steps
                ],
            )
    raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id}"})


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str):
    from cardre.cancellation import cancel_run as _cancel
    _cancel(run_id)
    return {"run_id": run_id, "status": "cancelling"}


@router.get("/{run_id}/manifest")
def get_run_manifest(run_id: str):
    registry = load_registry()
    for pid in registry:
        try:
            store = get_store_for_project(pid)
        except (ProjectNotFoundError, ProjectPathMissingError):
            continue
        run = store.get_run(run_id)
        if run is None:
            continue
        for art in store.list_artifacts():
            if art.artifact_type == "run_manifest" and art.metadata.get("run_id") == run_id:
                path = store.artifact_path(art)
                if path.exists():
                    import json
                    return json.loads(path.read_text())
        raise HTTPException(status_code=404, detail={"code": "MANIFEST_NOT_FOUND", "message": f"No manifest for run {run_id}"})
    raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id}"})
