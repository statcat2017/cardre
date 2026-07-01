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

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from cardre.config import CardreConfig
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError, GovernanceNotEnabled

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

        if run_scope == "branch" and not self._config.governance_enabled:
            raise GovernanceNotEnabled(
                "Branch execution requires CARDRE_GOVERNANCE=1. "
                "Set the environment variable to enable challenger governance."
            )

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
                        return self._build_summary(result.run_id)

            if run_scope == "to_node" and target_step_id:
                from cardre.services.evidence_resolver import EvidencePolicyService
                evidence = EvidencePolicyService(self._store)
                result = evidence.check_to_node_current(
                    plan_version_id, target_step_id, branch_id=branch_id,
                )
                if result.run_id is not None:
                    placeholder_id = self._create_persisted_run(
                        plan_version_id=plan_version_id,
                        run_scope=run_scope, branch_id=branch_id,
                        target_step_id=target_step_id, force=force,
                        requested_by=requested_by, request_id=request_id,
                    )
                    self._cancel_placeholder_run(
                        placeholder_id,
                        plan_version_id=plan_version_id,
                        execution_mode="to_node",
                        branch_id=branch_id,
                        target_step_id=target_step_id,
                        existing_run_id=result.run_id,
                        reason=f"for to-node {target_step_id}",
                    )
                    return self._build_summary(result.run_id)

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
        execution request from persisted fields.
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

        # Recover request fields from metadata_json or top-level columns
        metadata: JsonDict = {}
        if run.get("metadata_json"):
            metadata = json.loads(run["metadata_json"]) if isinstance(run["metadata_json"], str) else run["metadata_json"]

        run_scope = metadata.get("run_scope", "full_plan")
        branch_id = run.get("branch_id") or metadata.get("branch_id")
        target_step_id = run.get("target_step_id") or metadata.get("target_step_id")
        force = run.get("force", False) or metadata.get("force", False)

        return self._execute_existing_running_run(
            run_id=run_id,
            plan_version_id=plan_version_id,
            run_scope=run_scope,
            branch_id=branch_id,
            target_step_id=target_step_id,
            force=force,
        )

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _execute_existing_running_run(
        self,
        run_id: str,
        plan_version_id: str,
        run_scope: str,
        branch_id: str | None,
        target_step_id: str | None,
        force: bool,
    ) -> RunSummary:
        from cardre.execution.run_lifecycle import RunLifecycle
        from cardre.execution.executor import PlanExecutor

        executor = PlanExecutor(self._store)

        execution_mode = {
            "branch": "branch",
            "to_node": "to_node",
            "full_plan": "full_plan",
        }.get(run_scope, "full_plan")

        try:
            with RunLifecycle(
                store=self._store,
                run_id=run_id,
                plan_version_id=plan_version_id,
                execution_mode=execution_mode,
                branch_id=branch_id,
                target_step_id=target_step_id,
            ) as lifecycle:
                if run_scope == "to_node" and target_step_id:
                    executor.run_to_node(
                        plan_version_id, target_step_id, run_id,
                        force=force, branch_id=branch_id,
                    )
                else:
                    executor.run_plan_version(
                        plan_version_id, run_id,
                        force=force, branch_id=branch_id,
                    )
                lifecycle.finalise(
                    status="succeeded",
                    execution_mode=execution_mode,
                    branch_id=branch_id,
                    target_step_id=target_step_id,
                )
        except CardreError:
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
            raise CardreError(message, code=code, context={"plan_version_id": plan_version_id})
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
        return self._build_summary(run_id, executed_ids)

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
        return self._build_summary(run_id)

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

        Stores extra fields (run_scope, requested_by, request_id) in
        metadata_json when the runs table lacks dedicated columns.
        """
        run_id = str(uuid.uuid4())
        now = utc_now_iso()

        metadata: JsonDict = {"run_scope": run_scope}
        if requested_by:
            metadata["requested_by"] = requested_by
        if request_id:
            metadata["request_id"] = request_id
        metadata_json_str = json.dumps(metadata)

        columns = self._get_run_columns()

        insert_cols = ["run_id", "plan_version_id", "status", "started_at"]
        values: list[object] = [run_id, plan_version_id, "running", now]

        if "branch_id" in columns:
            insert_cols.append("branch_id")
            values.append(branch_id)
        if "target_step_id" in columns:
            insert_cols.append("target_step_id")
            values.append(target_step_id)
        if "force" in columns:
            insert_cols.append("force")
            values.append(1 if force else 0)
        if "heartbeat_at" in columns:
            insert_cols.append("heartbeat_at")
            values.append(now)
        if "metadata_json" in columns:
            insert_cols.append("metadata_json")
            values.append(metadata_json_str)

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
            conn.execute(
                f"INSERT INTO runs ({', '.join(insert_cols)}) "
                f"VALUES ({', '.join(['?'] * len(insert_cols))})",
                tuple(values),
            )
        return run_id

    def _get_run_columns(self) -> set[str]:
        rows = self._store.execute("PRAGMA table_info(runs)").fetchall()
        return {r["name"] for r in rows}

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
        from cardre.execution.run_lifecycle import finalise_run, RunFinalisation
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
        finalise_run(self._store, RunFinalisation(
            run_id=run_id,
            plan_version_id=plan_version_id,
            status="cancelled",
            execution_mode=execution_mode,
            finished_at=utc_now_iso(),
            branch_id=branch_id,
            target_step_id=target_step_id,
        ))

    def _build_summary(
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
