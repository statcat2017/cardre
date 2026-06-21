"""Run execution endpoints — async execution with polling."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.services.project_registry import get_store_for_project, load_registry, ProjectNotFoundError, ProjectPathMissingError
from cardre.services.run_orchestrator import execute_run, dispatch_run_async
from cardre.store import ProjectStore
from sidecar.models import RunRequest, RunResponse, RunStepsResponse, RunStepItem, ArtifactResponse

router = APIRouter(prefix="/runs", tags=["runs"])


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
    from cardre.errors import GovernanceNotEnabled

    store = get_store_for_project(body.project_id)

    pv = store.get_plan_version(body.plan_version_id)
    if pv is None:
        raise HTTPException(status_code=404, detail={"code": "PLAN_VERSION_NOT_FOUND", "message": "Plan version not found"})

    if body.run_scope == "branch":
        try:
            from cardre.store.project_store import _governance_enabled
            if not _governance_enabled():
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "GOVERNANCE_NOT_ENABLED",
                        "message": "Branch execution requires CARDRE_GOVERNANCE=1. Set the environment variable to enable challenger governance.",
                    },
                )
        except ImportError:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "GOVERNANCE_NOT_ENABLED",
                    "message": "Branch execution requires CARDRE_GOVERNANCE=1.",
                },
            )

    # Synchronous execution path
    if sync:
        try:
            run_id = execute_run(
                store=store,
                plan_version_id=body.plan_version_id,
                run_id=None,
                run_scope=body.run_scope,
                branch_id=body.branch_id,
                target_step_id=body.target_step_id,
                force=body.force,
            )
            executed_ids = [rs.step_id for rs in store.get_run_steps(run_id)]
            return _build_run_response(store, run_id, executed_ids)
        except ValueError as exc:
            scope_label = body.run_scope or "full"
            detail_code = f"{scope_label.upper()}_RUN_FAILED"
            raise HTTPException(status_code=400, detail={"code": detail_code, "message": str(exc)})
        except Exception:
            run_id = store.create_run(body.plan_version_id)
            store.finish_run(run_id, "failed")
            return _build_run_response(store, run_id)

    # Async (default): create run immediately, execute in background
    branch_kw = {"branch_id": body.branch_id} if body.branch_id else {}
    run_id = store.create_run(body.plan_version_id, **branch_kw)
    project_path = str(store.root)
    try:
        t = threading.Thread(
            target=dispatch_run_async,
            kwargs={
                "project_path": project_path,
                "plan_version_id": body.plan_version_id,
                "run_id": run_id,
                "force": body.force,
                "run_scope": body.run_scope,
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
