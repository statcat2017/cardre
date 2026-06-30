"""Run orchestrator — unified run dispatch for sync and async execution."""

from __future__ import annotations

from typing import Literal

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
    """Compatibility shim. Delegates to RunService — no independent policy.

    New code should call RunService.run_plan or RunService.execute_created_run
    directly. This exists so existing callers/tests that import
    run_orchestrator.execute_run keep working.
    """
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import RunRequest

    if run_id is None:
        response = RunService(store).run_plan(
            plan_version_id=plan_version_id,
            run_scope=run_scope,
            branch_id=branch_id,
            target_step_id=target_step_id,
            force=force,
            sync=True,
        )
        return response.run_id

    request = RunRequest(
        project_path=str(store.root),
        plan_version_id=plan_version_id,
        run_id=run_id,
        run_scope=run_scope,
        branch_id=branch_id,
        target_step_id=target_step_id,
        force=force,
    )
    response = RunService(store).execute_created_run(request)
    return response.run_id


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
