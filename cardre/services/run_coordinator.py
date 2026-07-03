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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

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
    from cardre.store.db import ProjectStore


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


class RunCoordinator:
    """Single entrypoint for run creation, execution, and dispatch.

    ``run()`` validates, creates/persists, and dispatches.
    ``execute_created_run(run_id)`` loads persisted request fields and
    executes, enabling async recovery.
    """

    def __init__(self, store: "ProjectStore") -> None:
        self._store = store
        self._config = CardreConfig.from_env()

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

        # Preflight short-circuit checks (sync runs fall through to
        # _execute_sync which records the RUN_SHORT_CIRCUITED diagnostic)
        if not force:
            if run_scope == "branch" and branch_id:
                from cardre.services.evidence_resolver import EvidencePolicyService
                evidence = EvidencePolicyService(self._store)
                result = evidence.check_branch_current(plan_version_id, branch_id)
                if result.run_id is not None:
                    if sync:
                        pass  # Fall through to _execute_sync
                    else:
                        placeholder_id = self._create_persisted_run(
                            plan_version_id=plan_version_id,
                            run_scope=run_scope, branch_id=branch_id,
                            target_step_id=target_step_id, force=force,
                            requested_by=requested_by, request_id=request_id,
                        )
                        self._cancel_placeholder_run(
                            placeholder_id,
                            plan_version_id=plan_version_id,
                            execution_mode="branch",
                            branch_id=branch_id,
                            existing_run_id=result.run_id,
                            reason="because branch has no stale steps",
                        )
                        return self.get_summary(result.run_id)

        # Recover stale runs for this plan_version
        for existing_run in run_repo.list_for_plan_version(plan_version_id=plan_version_id):
            if existing_run.get("status") == "running":
                self._maybe_recover_stale_run(existing_run)

        # Create run with all request fields persisted
        run_id = self._create_persisted_run(
            plan_version_id=plan_version_id,
            run_scope=run_scope, branch_id=branch_id,
            target_step_id=target_step_id, force=force,
            requested_by=requested_by, request_id=request_id,
        )

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

        from cardre.execution.run_lifecycle import RunLifecycle
        from cardre.execution.executor import PlanExecutor

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
                code="RUN_EXECUTION_FAILED",
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
        from cardre.execution.worker import RunRequest, ThreadRunDispatcher

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
        dispatcher = ThreadRunDispatcher()
        dispatcher.dispatch(request)
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
            run_repo.finish(run["run_id"], "interrupted")
            run_repo.append_diagnostic(run["run_id"], diag)

    def _is_stale(self, run: JsonDict) -> bool:
        if run.get("status") != "running":
            return False
        hb = run.get("heartbeat_at")
        if hb is None:
            return True
        try:
            hb_ts = datetime.fromisoformat(hb).replace(tzinfo=timezone.utc).timestamp()
            now_ts = datetime.now(timezone.utc).timestamp()
            return (now_ts - hb_ts) > self._config.stale_heartbeat_seconds
        except (ValueError, TypeError):
            return True

    def _cancel_placeholder_run(
        self,
        run_id: str,
        *,
        plan_version_id: str,
        execution_mode: str,
        branch_id: str | None = None,
        target_step_id: str | None = None,
        existing_run_id: str,
        reason: str,
    ) -> None:
        from cardre.execution.run_lifecycle import RunLifecycle
        from cardre.store.run_repo import RunRepository

        RunRepository(self._store).append_diagnostic(run_id, {
            "code": "RUN_SHORT_CIRCUITED",
            "message": (
                f"Run {run_id} short-circuited {reason} "
                f"(existing run {existing_run_id})"
            ),
            "severity": "info",
            "run_id": run_id,
            "plan_version_id": plan_version_id,
            "branch_id": branch_id,
            "created_at": utc_now_iso(),
        })
        lifecycle = RunLifecycle(
            store=self._store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            execution_mode=execution_mode,
            branch_id=branch_id,
            target_step_id=target_step_id,
        )
        lifecycle.finalise(
            status="cancelled",
            execution_mode=execution_mode,
            branch_id=branch_id,
            target_step_id=target_step_id,
        )

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


__all__ = ["RunCoordinator", "RunSummary"]
