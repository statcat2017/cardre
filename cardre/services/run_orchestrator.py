"""Run orchestrator — unified run dispatch for sync and async execution."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore


def _fail_run_if_running(store: ProjectStore, run_id: str) -> None:
    try:
        run = store.get_run(run_id)
        if run and run.get("status") == "running":
            store.finish_run(run_id, "failed")
    except Exception:
        pass


def execute_run(
    store: ProjectStore,
    plan_version_id: str,
    run_id: str | None = None,
    run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan",
    branch_id: str | None = None,
    target_step_id: str | None = None,
    force: bool = False,
) -> str:
    """Execute a run synchronously. Returns the run_id."""
    from cardre.errors import GovernanceNotEnabled

    if run_scope == "branch":
        from cardre.store.project_store import _governance_enabled
        if not _governance_enabled():
            raise GovernanceNotEnabled(
                "Branch execution requires CARDRE_GOVERNANCE=1. "
                "Set the environment variable to enable challenger governance."
            )

    executor = PlanExecutor(NodeRegistry.with_defaults())
    if run_scope == "branch" and branch_id:
        result_id = executor.run_branch(store, plan_version_id, branch_id, run_id=run_id, force=force)
        if run_id is not None and result_id != run_id:
            store.finish_run(run_id, "cancelled")
            return run_id
        return result_id
    if run_scope == "to_node" and target_step_id:
        result_id = executor.run_to_node(store, plan_version_id, target_step_id, run_id=run_id, force=force)
    else:
        result_id = executor.run_plan_version(store, plan_version_id, run_id=run_id, force=force)
    if run_id is not None and result_id != run_id:
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
    """Execute a run in a background thread."""
    store = ProjectStore(project_path)
    try:
        execute_run(
            store=store,
            plan_version_id=plan_version_id,
            run_id=run_id,
            run_scope=run_scope,
            branch_id=branch_id,
            target_step_id=target_step_id,
            force=force,
        )
    except BaseException:
        import traceback
        print(f"[sidecar] dispatch_run_async({run_id}) failed: {traceback.format_exc()}", flush=True)
        _fail_run_if_running(store, run_id)
