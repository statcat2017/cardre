"""Run orchestrator — unified run dispatch for sync and async execution."""

from __future__ import annotations

from typing import Literal

from cardre.audit import utc_now_iso
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore


def execute_run(
    store: ProjectStore,
    plan_version_id: str,
    run_id: str | None = None,
    run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan",
    branch_id: str | None = None,
    target_step_id: str | None = None,
    force: bool = False,
) -> str:
    """Execute a run synchronously. Returns the run_id.

    Branch evidence is prepared here via EvidencePolicyService (the
    single source of truth) and passed into executor.run_branch as
    branch_ctx. The executor does not prepare evidence itself.
    """
    executor = PlanExecutor(NodeRegistry.with_defaults())

    if run_scope == "branch" and branch_id:
        from cardre.services.evidence_policy import EvidencePolicyService
        ctx = EvidencePolicyService(store).prepare_branch_evidence(
            plan_version_id, branch_id, force=force,
        )
        if not force and ctx.short_circuit_run_id is not None:
            if run_id is not None:
                store.append_run_diagnostic(run_id, {
                    "code": "RUN_SHORT_CIRCUITED",
                    "message": f"Run {run_id} short-circuited because branch has no stale steps (existing run {ctx.short_circuit_run_id})",
                    "severity": "info",
                    "category": "lifecycle",
                    "run_id": run_id,
                    "plan_version_id": plan_version_id,
                    "branch_id": branch_id,
                    "created_at": utc_now_iso(),
                })
                store.finish_run(run_id, "cancelled")
                return run_id
            return ctx.short_circuit_run_id
        result_id = executor.run_branch(
            store, plan_version_id, branch_id,
            run_id=run_id, force=force, branch_ctx=ctx,
        )
        return _handle_short_circuit(store, run_id, result_id,
                                      plan_version_id, branch_id)

    if run_scope == "to_node" and target_step_id:
        result_id = executor.run_to_node(
            store, plan_version_id, target_step_id,
            run_id=run_id, force=force, branch_id=branch_id,
        )
    else:
        result_id = executor.run_plan_version(
            store, plan_version_id, run_id=run_id, force=force,
        )
    return _handle_short_circuit(store, run_id, result_id,
                                  plan_version_id, branch_id)


def _handle_short_circuit(
    store: ProjectStore, run_id: str | None, result_id: str,
    plan_version_id: str, branch_id: str | None,
) -> str:
    """If the executor returned a different run_id, record the
    short-circuit and cancel the placeholder run."""
    if run_id is not None and result_id != run_id:
        store.append_run_diagnostic(run_id, {
            "code": "RUN_SHORT_CIRCUITED",
            "message": f"Run {run_id} short-circuited (existing run {result_id})",
            "severity": "info",
            "category": "lifecycle",
            "run_id": run_id,
            "plan_version_id": plan_version_id,
            "branch_id": branch_id,
            "created_at": utc_now_iso(),
        })
        store.finish_run(run_id, "cancelled")
        return run_id
    return result_id


def dispatch_run_async(
    project_path: str,
    plan_version_id: str,
    run_id: str,
    run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan",
    branch_id: str | None = None,
    target_step_id: str | None = None,
    force: bool = False,
) -> None:
    """Compatibility wrapper that executes the RunWorker body inline.

    New async dispatch should go through ``RunService`` + ``RunDispatcher``.
    Existing tests monkeypatch ``execute_run`` in this module; the worker
    calls it via :meth:`RunWorker._invoke_executor`, so those patches
    continue to take effect. The diagnostic code recorded on failure is
    ``RUN_WORKER_FAILED`` (see :mod:`run_worker`); older tests asserted
    ``RUN_DISPATCH_FAILED`` and are updated alongside this change.
    """
    from cardre.services.run_worker import RunWorker, RunRequest

    request = RunRequest(
        project_path=project_path,
        plan_version_id=plan_version_id,
        run_id=run_id,
        run_scope=run_scope,
        branch_id=branch_id,
        target_step_id=target_step_id,
        force=force,
    )
    RunWorker().execute(request)
