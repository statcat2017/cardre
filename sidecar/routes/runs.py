"""Run execution endpoints — async execution with polling."""

from __future__ import annotations

from dataclasses import asdict
from json import JSONDecodeError

from fastapi import APIRouter, HTTPException, Query

from cardre.errors import CardreError
from cardre.evidence import ArtifactEvidenceReader, EvidenceError
from cardre.services.evidence_policy import EvidencePolicyService
from cardre.services.project_registry import get_store_for_project
from cardre.services.run_service import RunService
from sidecar.models import RunDiagnostic, RunRequest, RunResponse, RunStepsResponse, RunStepItem

router = APIRouter(prefix="/runs", tags=["runs"])


# ------------------------------------------------------------------
# Compatibility wrappers for tests that import these directly
# ------------------------------------------------------------------


def _is_branch_current(store, plan_version_id, branch_id):
    try:
        svc = EvidencePolicyService(store)
        result = svc.check_branch_current(plan_version_id, branch_id)
        return result.run_id
    except Exception:
        return None


def _is_to_node_current(store, plan_version_id, target_step_id, branch_id=None):
    try:
        svc = EvidencePolicyService(store)
        result = svc.check_to_node_current(plan_version_id, target_step_id, branch_id=branch_id)
        return result.run_id
    except Exception:
        return None


@router.post("", response_model=RunResponse, status_code=201)
def run_plan(body: RunRequest, sync: bool = Query(default=False, description="Execute synchronously (for tests)")):
    store = get_store_for_project(body.project_id)
    service = RunService(store)

    try:
        result = service.run_plan(
            plan_version_id=body.plan_version_id,
            run_scope=body.run_scope or "full_plan",
            branch_id=body.branch_id,
            target_step_id=body.target_step_id,
            force=body.force,
            sync=sync,
        )
    except CardreError as exc:
        exc.context.setdefault("project_id", body.project_id)
        exc.context.setdefault("plan_version_id", body.plan_version_id)
        exc.context.setdefault("run_scope", body.run_scope or "full")
        raise

    return RunResponse(
        run_id=result.run_id,
        plan_version_id=result.plan_version_id,
        status=result.status,
        started_at=result.started_at,
        finished_at=result.finished_at,
        step_count=result.step_count,
        branch_id=result.branch_id,
        executed_step_ids=result.executed_step_ids or [],
        diagnostics=[RunDiagnostic(**d) for d in (result.diagnostics or [])],
        latest_error=RunDiagnostic(**result.latest_error) if result.latest_error else None,
        heartbeat_at=result.heartbeat_at,
        is_stale=result.is_stale,
    )


# ------------------------------------------------------------------
# Project-scoped run endpoints
# ------------------------------------------------------------------


@router.get("/project/{project_id}/runs/{run_id}", response_model=RunResponse)
def get_project_run(project_id: str, run_id: str):
    store = get_store_for_project(project_id)
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id} in project {project_id}"})
    service = RunService(store)
    result = service._build_response(run_id)
    return RunResponse(
        run_id=result.run_id,
        plan_version_id=result.plan_version_id,
        status=result.status,
        started_at=result.started_at,
        finished_at=result.finished_at,
        step_count=result.step_count,
        branch_id=result.branch_id,
        executed_step_ids=result.executed_step_ids or [],
        diagnostics=[RunDiagnostic(**d) for d in (result.diagnostics or [])],
        latest_error=RunDiagnostic(**result.latest_error) if result.latest_error else None,
        heartbeat_at=result.heartbeat_at,
        is_stale=result.is_stale,
    )


@router.get("/project/{project_id}/runs/{run_id}/steps", response_model=RunStepsResponse)
def get_project_run_steps(project_id: str, run_id: str):
    store = get_store_for_project(project_id)
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id} in project {project_id}"})
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


@router.get("/project/{project_id}/runs/{run_id}/manifest")
def get_project_run_manifest(project_id: str, run_id: str):
    store = get_store_for_project(project_id)
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id} in project {project_id}"})
    reader = ArtifactEvidenceReader(store)
    for art in store.list_artifacts():
        if art.artifact_type == "run_manifest" and art.metadata.get("run_id") == run_id:
            try:
                manifest = reader.read_run_manifest(art.artifact_id)
            except (EvidenceError, JSONDecodeError, OSError) as e:
                raise CardreError(
                    "Run manifest could not be read.",
                    code="RUN_MANIFEST_UNREADABLE",
                    context={"run_id": run_id, "artifact_id": art.artifact_id},
                    severity="error",
                ) from e
            return asdict(manifest)
    raise HTTPException(status_code=404, detail={"code": "MANIFEST_NOT_FOUND", "message": f"No manifest for run {run_id}"})
