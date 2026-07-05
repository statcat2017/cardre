"""RunCoordinator — validated run creation, execution, and dispatch.

``RunCoordinator.run()`` validates the request, creates a run with all
request fields persisted in the database, and dispatches sync or async.
``RunCoordinator.execute_created_run(run_id)`` loads the request fields
from the database and executes — making it recoverable for async dispatch
and crash recovery.

The short-circuit logic, placeholder cancellation, sync/async dispatch,
and stale-run recovery carry over from v1 ``run_service.py``.

Class renamed to ``RunCoordinator`` (free rename, clearer name).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from cardre.api.errors import RUN_EXECUTION_FAILED
from cardre.config import CardreConfig
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import (
    CardreError,
    GovernanceNotEnabled,
    PlanVersionNotCommittedError,
    RunScopeNotAvailableForLaunch,
)
from cardre.domain.run import RunStepStatus

if TYPE_CHECKING:
    from cardre.domain.diagnostics import JsonDict
    from cardre.execution.worker import RunDispatcher
    from cardre.store.db import ProjectStore


# Module-level singleton dispatcher — app-scoped, not per-request (#4).
_global_dispatcher: RunDispatcher | None = None


def _get_global_dispatcher() -> RunDispatcher:
    global _global_dispatcher
    if _global_dispatcher is None:
        from cardre.execution.worker import ThreadRunDispatcher
        _global_dispatcher = ThreadRunDispatcher()
    return _global_dispatcher


@dataclass
class RunSummary:
    """Summary response for a run."""
    run_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    step_count: int = 0
    branch_id: str | None = None
    executed_step_ids: list[str] | None = None
    diagnostics: list[JsonDict] | None = None
    latest_error: JsonDict | None = None
    heartbeat_at: str | None = None
    is_stale: bool = False


@dataclass
class RunPlanDecision:
    """Typed plan decision computed before dispatch (#212).

    ``kind`` is one of:
    - ``execute``: create a run and execute/dispatch it;
    - ``short_circuit``: return the existing run without new work;
    - ``reject``: the request is invalid; the caller has already raised.

    Toggling ``sync`` changes only where ``execute`` work runs, never
    what work is performed.
    """
    kind: Literal["execute", "short_circuit", "reject"]
    existing_run_id: str | None = None
    diagnostics: list[JsonDict] | None = None


class RunCoordinator:
    """Single entrypoint for run creation, execution, and dispatch.

    ``run()`` validates, creates/persists, and dispatches.
    ``execute_created_run(run_id)`` loads persisted request fields and
    executes, enabling async recovery.
    """

    def __init__(
        self,
        store: ProjectStore,
        dispatcher: RunDispatcher | None = None,
    ) -> None:
        self._store = store
        self._config = CardreConfig.from_env()
        if dispatcher is not None:
            self._dispatcher = dispatcher
        else:
            self._dispatcher = _get_global_dispatcher()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        plan_version_id: str,
        *,
        run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan",
        branch_id: str | None = None,
        target_step_id: str | None = None,
        force: bool = False,
        sync: bool = False,
        requested_by: str | None = None,
        request_id: str | None = None,
    ) -> RunSummary:
        """Validate, create/reuse, and dispatch a run. Returns RunSummary."""
        from cardre.store.plan_repo import PlanRepository
        from cardre.store.run_repo import RunRepository

        plan_repo = PlanRepository(self._store)
        run_repo = RunRepository(self._store)

        pv = plan_repo.get_version(plan_version_id)
        if pv is None:
            raise CardreError(
                f"Plan version {plan_version_id} not found",
                code="PLAN_VERSION_NOT_FOUND",
                context={"plan_version_id": plan_version_id},
            )
        if not pv.get("is_committed", False):
            raise PlanVersionNotCommittedError(
                f"Plan version {plan_version_id} must be committed before execution.",
                context={"plan_version_id": plan_version_id},
            )

        if run_scope == "branch" and not self._config.governance_enabled:
            raise GovernanceNotEnabled(
                "Branch execution requires CARDRE_GOVERNANCE=1. "
                "Set the environment variable to enable challenger governance."
            )

        if run_scope == "to_node":
            self._raise_run_scope_not_available(run_scope, target_step_id)

        # Compute the plan decision once — sync and async must agree.
        decision = self._plan_decision(
            plan_version_id=plan_version_id,
            run_scope=run_scope,
            branch_id=branch_id,
            target_step_id=target_step_id,
            force=force,
            requested_by=requested_by,
            request_id=request_id,
            run_repo=run_repo,
        )

        if decision.kind == "short_circuit":
            assert decision.existing_run_id is not None
            return self.get_summary(decision.existing_run_id)

        # Create run with all request fields persisted
        try:
            run_id = self._create_persisted_run(
                plan_version_id=plan_version_id,
                run_scope=run_scope, branch_id=branch_id,
                target_step_id=target_step_id, force=force,
                requested_by=requested_by, request_id=request_id,
            )
        except CardreError as exc:
            if exc.code == "EVIDENCE_POLICY_CURRENT":
                existing_run_id = exc.context.get("existing_run_id")
                if isinstance(existing_run_id, str) and existing_run_id:
                    return self.get_summary(existing_run_id)
            raise

        if sync:
            return self._execute_sync(run_id, plan_version_id, run_scope, branch_id, target_step_id, force)

        return self._dispatch_async(run_id, plan_version_id, run_scope, branch_id, target_step_id, force)

    def execute_created_run(self, run_id: str) -> RunSummary:
        """Execute a previously created run, recovering request fields from the DB.

        This is the recoverable entrypoint for async dispatch and crash
        recovery. Loads the run record from the database and rebuilds the
        execution request from persisted columns.

        ``metadata_json`` holds execution metadata only (active_step_id,
        runtime warnings, diagnostic payload) — never request fields.
        """
        from cardre.store.run_repo import RunRepository

        run_repo = RunRepository(self._store)
        run = run_repo.get(run_id)
        if run is None:
            raise CardreError(
                f"Run {run_id} not found",
                code="RUN_NOT_FOUND",
                context={"run_id": run_id},
            )
        if run["status"] != "running":
            raise CardreError(
                f"Run {run_id} is not running.",
                code="RUN_NOT_RUNNING",
                context={"run_id": run_id, "status": run["status"]},
            )

        plan_version_id = run["plan_version_id"]

        return self._execute_existing_running_run(
            run_id=run_id,
            plan_version_id=plan_version_id,
            run_scope=run["run_scope"],
            branch_id=run["branch_id"],
            target_step_id=run["target_step_id"],
            force=bool(run["force"]),
        )

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _plan_decision(
        self,
        *,
        plan_version_id: str,
        run_scope: str,
        branch_id: str | None,
        target_step_id: str | None,
        force: bool,
        requested_by: str | None,
        request_id: str | None,
        run_repo: object,
    ) -> RunPlanDecision:
        """Compute the run plan decision once, independent of sync/async (#212).

        Sync and async must perform the same work for the same decision.
        A ``short_circuit`` decision returns the existing run without
        creating a placeholder.
        """
        if not force and run_scope == "branch" and branch_id:
            from cardre.services.evidence_resolver import EvidencePolicyService
            evidence = EvidencePolicyService(self._store)
            result = evidence.check_branch_current(plan_version_id, branch_id)
            if result.status == "current" and result.run_id is not None:
                return RunPlanDecision(
                    kind="short_circuit",
                    existing_run_id=result.run_id,
                )
            if result.status == "error":
                raise CardreError(
                    f"Evidence policy check failed for branch {branch_id!r}",
                    code="EVIDENCE_POLICY_ERROR",
                    context={
                        "plan_version_id": plan_version_id,
                        "branch_id": branch_id,
                        "diagnostics": result.diagnostics,
                    },
                )
        return RunPlanDecision(kind="execute")

    def _raise_run_scope_not_available(
        self,
        run_scope: str,
        target_step_id: str | None = None,
    ) -> None:
        """Raise RunScopeNotAvailableForLaunch with a consistent message and context.

        Suggests ``full_plan`` as the alternative (branch may not be available
        when governance is disabled).
        """
        ctx: dict[str, object] = {"run_scope": run_scope}
        if target_step_id is not None:
            ctx["target_step_id"] = target_step_id
        raise RunScopeNotAvailableForLaunch(
            f"run_scope={run_scope!r} is currently disabled for launch. Use full_plan instead.",
            context=ctx,
        )

    def _execute_existing_running_run(
        self,
        run_id: str,
        plan_version_id: str,
        run_scope: str,
        branch_id: str | None,
        target_step_id: str | None,
        force: bool,
    ) -> RunSummary:
        execution_mode = {
            "branch": "branch",
            "full_plan": "full_plan",
        }.get(run_scope, "full_plan")

        if run_scope == "to_node":
            from cardre.store.run_repo import RunRepository
            RunRepository(self._store).finish(run_id, "failed")
            self._raise_run_scope_not_available(run_scope, target_step_id)

        from cardre.execution.executor import PlanExecutor
        from cardre.execution.run_lifecycle import RunLifecycle

        executor = PlanExecutor(self._store)

        try:
            with RunLifecycle(
                store=self._store,
                run_id=run_id,
                plan_version_id=plan_version_id,
                execution_mode=execution_mode,
                branch_id=branch_id,
                target_step_id=target_step_id,
            ) as lifecycle:
                executor.run_plan_version(
                    plan_version_id, run_id,
                    force=force, branch_id=branch_id,
                )
                from cardre.store.run_step_repo import RunStepRepository
                has_failure = any(
                    rs.status == RunStepStatus.FAILED
                    for rs in RunStepRepository(self._store).get_for_run(run_id)
                )
                lifecycle.finalise(
                    status="failed" if has_failure else "succeeded",
                    execution_mode=execution_mode,
                    branch_id=branch_id,
                    target_step_id=target_step_id,
                )
        except CardreError:
            raise
        except Exception as exc:
            raise CardreError(
                f"Run execution failed: {exc}",
                code=RUN_EXECUTION_FAILED,
                context={
                    "plan_version_id": plan_version_id,
                    "run_scope": run_scope,
                    "branch_id": branch_id,
                },
            ) from exc

        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(self._store)
        executed_ids = [rs.step_id for rs in rs_repo.get_for_run(run_id)]
        return self.get_summary(run_id, executed_ids)

    def _execute_sync(
        self, run_id: str, plan_version_id: str,
        run_scope: str, branch_id: str | None, target_step_id: str | None,
        force: bool,
    ) -> RunSummary:
        return self._execute_existing_running_run(
            run_id, plan_version_id, run_scope, branch_id, target_step_id, force,
        )

    def _dispatch_async(
        self, run_id: str, plan_version_id: str,
        run_scope: str, branch_id: str | None, target_step_id: str | None,
        force: bool,
    ) -> RunSummary:
        from cardre.execution.worker import RunRequest

        project_path = str(self._store.root)
        request = RunRequest(
            project_path=project_path,
            plan_version_id=plan_version_id,
            run_id=run_id,
            run_scope=run_scope,  # type: ignore[arg-type]
            branch_id=branch_id,
            target_step_id=target_step_id,
            force=force,
        )
        try:
            self._dispatcher.dispatch(request)
        except CardreError:
            from cardre.store.run_repo import RunRepository
            with self._store.transaction("IMMEDIATE"):
                RunRepository(self._store).append_diagnostic(run_id, {
                    "code": "RUN_DISPATCH_FAILED",
                    "message": "Dispatch failed; run marked as failed.",
                    "severity": "error",
                    "run_id": run_id,
                    "plan_version_id": plan_version_id,
                    "created_at": utc_now_iso(),
                })
                RunRepository(self._store).finish(run_id, "failed")
            raise
        return self.get_summary(run_id)

    # ------------------------------------------------------------------
    # Run creation with persisted request fields
    # ------------------------------------------------------------------

    def _create_persisted_run(
        self,
        plan_version_id: str,
        run_scope: str,
        branch_id: str | None,
        target_step_id: str | None,
        force: bool,
        requested_by: str | None = None,
        request_id: str | None = None,
    ) -> str:
        """Create a run in the database with all request fields persisted.

        Request fields (run_scope, branch_id, target_step_id, force,
        requested_by, request_id) are stored in dedicated columns.
        ``metadata_json`` is reserved for execution metadata only.
        """
        from cardre.store.run_repo import RunRepository

        run_repo = RunRepository(self._store)

        with self._store.transaction("IMMEDIATE") as conn:
            if not force and run_scope == "branch" and branch_id:
                from cardre.services.evidence_resolver import EvidencePolicyService

                evidence = EvidencePolicyService(self._store)
                result = evidence.check_branch_current(plan_version_id, branch_id)
                if result.status == "current" and result.run_id is not None:
                    raise CardreError(
                        "Branch already has a current run; short-circuiting.",
                        code="EVIDENCE_POLICY_CURRENT",
                        context={
                            "plan_version_id": plan_version_id,
                            "branch_id": branch_id,
                            "existing_run_id": result.run_id,
                        },
                    )
                if result.status == "error":
                    raise CardreError(
                        f"Evidence policy check failed for branch {branch_id!r}",
                        code="EVIDENCE_POLICY_ERROR",
                        context={
                            "plan_version_id": plan_version_id,
                            "branch_id": branch_id,
                            "diagnostics": result.diagnostics,
                        },
                    )

            for existing_run in run_repo.list_for_plan_version(plan_version_id=plan_version_id):
                if existing_run.get("status") == "running" and self._is_stale(existing_run):
                    active_step_id = run_repo.get_active_step(existing_run["run_id"])
                    diag: JsonDict = {
                        "code": "RUN_RECOVERED_STALE",
                        "message": f"Run {existing_run['run_id']} was stuck in 'running' with stale heartbeat — recovered as interrupted.",
                        "severity": "error",
                        "run_id": existing_run["run_id"],
                        "plan_version_id": existing_run.get("plan_version_id", ""),
                        "created_at": utc_now_iso(),
                    }
                    if active_step_id is not None:
                        diag["active_step_id"] = active_step_id
                        diag["message"] = (
                            f"Run {existing_run['run_id']} was stuck in 'running' with stale heartbeat "
                            f"(last active step: {active_step_id}) — recovered as interrupted."
                        )
                    run_repo.finish(existing_run["run_id"], "interrupted")
                    run_repo.append_diagnostic(existing_run["run_id"], diag)

            if not force:
                existing = conn.execute(
                    "SELECT 1 FROM runs WHERE plan_version_id = ? AND finished_at IS NULL",
                    (plan_version_id,),
                ).fetchone()
                if existing is not None:
                    raise CardreError(
                        f"A run is already in progress for plan_version_id={plan_version_id!r}",
                        code="CONCURRENT_RUN",
                    )
            run_id = run_repo.create(
                plan_version_id,
                run_scope=run_scope,
                branch_id=branch_id,
                target_step_id=target_step_id,
                force=force,
                requested_by=requested_by,
                request_id=request_id,
            )
        return run_id

    # ------------------------------------------------------------------
    # Stale-run recovery
    # ------------------------------------------------------------------

    def _maybe_recover_stale_run(self, run: JsonDict) -> None:
        if self._is_stale(run):
            from cardre.store.run_repo import RunRepository
            run_repo = RunRepository(self._store)

            active_step_id = run_repo.get_active_step(run["run_id"])
            diag: JsonDict = {
                "code": "RUN_RECOVERED_STALE",
                "message": f"Run {run['run_id']} was stuck in 'running' with stale heartbeat — recovered as interrupted.",
                "severity": "error",
                "run_id": run["run_id"],
                "plan_version_id": run.get("plan_version_id", ""),
                "created_at": utc_now_iso(),
            }
            if active_step_id is not None:
                diag["active_step_id"] = active_step_id
                diag["message"] = (
                    f"Run {run['run_id']} was stuck in 'running' with stale heartbeat "
                    f"(last active step: {active_step_id}) — recovered as interrupted."
                )
            with self._store.transaction("IMMEDIATE"):
                run_repo.finish(run["run_id"], "interrupted")
                run_repo.append_diagnostic(run["run_id"], diag)

    def _is_stale(self, run: JsonDict) -> bool:
        if run.get("status") != "running":
            return False
        hb = run.get("heartbeat_at")
        if hb is None:
            return True
        try:
            hb_ts = datetime.fromisoformat(hb).replace(tzinfo=UTC).timestamp()
            now_ts = datetime.now(UTC).timestamp()
            return (now_ts - hb_ts) > self._config.stale_heartbeat_seconds
        except (ValueError, TypeError):
            return True

    def get_summary(
        self, run_id: str, executed_ids: list[str] | None = None,
    ) -> RunSummary:
        from cardre.store.run_repo import RunRepository
        from cardre.store.run_step_repo import RunStepRepository

        run_repo = RunRepository(self._store)
        rs_repo = RunStepRepository(self._store)

        run = run_repo.get(run_id)
        if run is None:
            raise CardreError(
                f"Run {run_id} not found",
                code="RUN_NOT_FOUND",
                context={"run_id": run_id},
            )

        steps = rs_repo.get_for_run(run_id)
        diags = run_repo.get_diagnostics(run_id)
        latest_error = None
        for d in diags:
            if d.get("severity") == "error":
                latest_error = d

        return RunSummary(
            run_id=run["run_id"],
            plan_version_id=run["plan_version_id"],
            status=run["status"],
            started_at=run["started_at"],
            finished_at=run.get("finished_at"),
            step_count=len(steps),
            branch_id=run.get("branch_id"),
            executed_step_ids=executed_ids or [],
            diagnostics=diags,
            latest_error=latest_error,
            heartbeat_at=run.get("heartbeat_at"),
            is_stale=self._is_stale(run),
        )


__all__ = ["RunCoordinator", "RunPlanDecision", "RunSummary"]
