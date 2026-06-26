"""Run execution endpoints — async execution with polling."""
from __future__ import annotations

import threading
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query

from cardre.errors import CardreError
from cardre.executor import PlanExecutor
from cardre.evidence import ArtifactEvidenceReader
from cardre.registry import NodeRegistry
from cardre.services.branch_evidence import BranchEvidenceResolver
from cardre.services.project_registry import get_store_for_project, load_registry, ProjectNotFoundError, ProjectPathMissingError
from cardre.services.run_orchestrator import execute_run, dispatch_run_async
from cardre.store import ProjectStore
from sidecar.models import RunDiagnostic, RunRequest, RunResponse, RunStepsResponse, RunStepItem

router = APIRouter(prefix="/runs", tags=["runs"])


def _is_branch_current(store, plan_version_id, branch_id):
    """Check if a branch run would short-circuit (no stale steps, existing successful run)."""
    try:
        resolver = BranchEvidenceResolver(PlanExecutor(NodeRegistry.with_defaults()))
        ctx = resolver.prepare_branch_run(store, branch_id, plan_version_id, force=False)
        if ctx.short_circuit_run_id is not None:
            return ctx.short_circuit_run_id
    except CardreError as exc:
        import logging
        logging.getLogger(__name__).warning(
            "_is_branch_current: %s (code=%s, branch_id=%s)", exc.message, exc.code, branch_id,
        )
    except Exception:
        pass
    return None


def _is_to_node_current(store, plan_version_id, target_step_id, branch_id=None):
    """Check if a to_node run would short-circuit (all closure steps non-stale)."""
    try:
        from cardre.staleness import compute_staleness
        from cardre.step_graph import ancestor_closure
        steps = store.get_plan_version_steps(plan_version_id)
        step_by_id = {s.step_id: s for s in steps}
        if target_step_id not in step_by_id:
            return None
        ancestors = ancestor_closure(target_step_id, steps)
        closure = ancestors | {target_step_id}
        closure_steps = [s for s in steps if s.step_id in closure]
        staleness = compute_staleness(store, plan_version_id, branch_id=branch_id)
        if all(not staleness.get(s.step_id, True) for s in closure_steps):
            existing_run_id = store.get_latest_successful_run_id(plan_version_id, branch_id=branch_id)
            if existing_run_id is not None:
                return existing_run_id
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "_is_to_node_current preflight degraded for "
            "plan_version_id=%s target_step_id=%s branch_id=%s: %s",
            plan_version_id, target_step_id, branch_id, exc,
        )
    return None


def _build_run_response(store: ProjectStore, run_id: str, executed_ids: list[str] | None = None) -> RunResponse:
    run = store.get_run(run_id)
    steps = store.get_run_steps(run_id)
    diags = store.get_run_diagnostics(run_id)
    latest_error = None
    for d in diags:
        if d.get("severity") == "error":
            latest_error = d
    return RunResponse(
        run_id=run["run_id"],
        plan_version_id=run["plan_version_id"],
        status=run["status"],
        started_at=run["started_at"],
        finished_at=run.get("finished_at"),
        step_count=len(steps),
        branch_id=run.get("branch_id"),
        executed_step_ids=executed_ids or [],
        diagnostics=[RunDiagnostic(**d) for d in diags],
        latest_error=RunDiagnostic(**latest_error) if latest_error else None,
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
        except CardreError as exc:
            exc.context.setdefault("project_id", body.project_id)
            exc.context.setdefault("plan_version_id", body.plan_version_id)
            exc.context.setdefault("run_scope", body.run_scope or "full")
            raise
        except ValueError as exc:
            msg = str(exc)
            if ":" in msg:
                code, message = msg.split(":", 1)
                code = code.strip()
                message = message.strip()
            else:
                code = "RUN_VALIDATION_FAILED"
                message = msg
            raise HTTPException(status_code=400, detail={"code": code, "message": message})
        except Exception as exc:
            raise CardreError(
                f"Run execution failed: {exc}",
                code="RUN_EXECUTION_FAILED",
                context={
                    "project_id": body.project_id,
                    "plan_version_id": body.plan_version_id,
                    "run_scope": body.run_scope,
                    "branch_id": body.branch_id,
                },
            ) from exc

    # Async (default): create run immediately, execute in background
    branch_kw = {"branch_id": body.branch_id} if body.branch_id else {}

    # Preflight: check if branch is already current (no stale steps)
    if not body.force and body.run_scope == "branch" and body.branch_id:
        existing_run_id = _is_branch_current(store, body.plan_version_id, body.branch_id)
        if existing_run_id is not None:
            return _build_run_response(store, existing_run_id)

    # Preflight: check if to_node closure is already current
    if not body.force and body.run_scope == "to_node" and body.target_step_id:
        existing_run_id = _is_to_node_current(store, body.plan_version_id, body.target_step_id, branch_id=body.branch_id)
        if existing_run_id is not None:
            return _build_run_response(store, existing_run_id)

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
    except Exception as exc:
        store.finish_run(run_id, "failed")
        raise CardreError(
            f"Failed to start background run thread: {exc}",
            code="RUN_DISPATCH_FAILED",
            context={
                "project_id": body.project_id,
                "plan_version_id": body.plan_version_id,
                "run_id": run_id,
                "run_scope": body.run_scope,
                "branch_id": body.branch_id,
            },
        ) from exc
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
    from json import JSONDecodeError
    from cardre.evidence import EvidenceError

    registry = load_registry()
    for pid in registry:
        try:
            store = get_store_for_project(pid)
        except (ProjectNotFoundError, ProjectPathMissingError):
            continue
        run = store.get_run(run_id)
        if run is None:
            continue
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
    raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": f"No run with ID {run_id}"})
