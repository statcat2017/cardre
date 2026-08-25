"""SubmitRun — validate, create, and dispatch a new run."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.application.ports.run_dispatcher import RunDispatcherPort, RunRequest


@dataclass
class SubmitRunCommand:
    plan_version_id: str
    run_scope: str = "full_plan"
    force: bool = False
    sync: bool = False


@dataclass
class SubmitRunResult:
    run_id: str
    status: str


class SubmitRun:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        dispatcher: RunDispatcherPort,
        execute_run: Any,
        finalize_run: Any,
        project_id: str | None = None,
        stale_heartbeat_seconds: int = 300,
    ) -> None:
        self._uow_factory = uow_factory
        self._dispatcher = dispatcher
        self._execute_run = execute_run
        self._finalize_run = finalize_run
        self._project_id = project_id
        self._stale_heartbeat_seconds = stale_heartbeat_seconds

    def __call__(self, command: SubmitRunCommand) -> SubmitRunResult:
        self._validate_command(command)
        uow = self._uow_factory()
        try:
            pv = uow.plans.get_version(command.plan_version_id)
        finally:
            uow.close()

        if pv is None:
            from cardre.domain.errors import CardreError, ErrorCode
            raise CardreError(
                f"Plan version {command.plan_version_id!r} not found",
                code=ErrorCode.PLAN_VERSION_NOT_FOUND,
                context={"plan_version_id": command.plan_version_id},
            )
        if not getattr(pv, "is_committed", False):
            from cardre.domain.errors import CardreError, ErrorCode
            raise CardreError(
                f"Plan version {command.plan_version_id!r} is not committed",
                code=ErrorCode.PLAN_VERSION_NOT_COMMITTED,
                context={"plan_version_id": command.plan_version_id},
            )

        self._sweep_stale()

        # Atomic concurrent-run guard: check + insert happen in one BEGIN
        # IMMEDIATE transaction, so two concurrent submissions cannot both
        # observe "no active run" and both create one. The dispatch intent is
        # committed in the same transaction, so a crash before the in-memory
        # dispatch cannot strand the run: startup reconciliation drains
        # pending dispatch rows.
        uow3 = self._uow_factory()
        try:
            run_id = uow3.runs.create_if_no_active_run(
                command.plan_version_id,
                run_scope=command.run_scope,
                force=command.force,
            )
            if run_id is None:
                from cardre.domain.errors import CardreError, ErrorCode

                raise CardreError(
                    f"Plan version {command.plan_version_id!r} already has "
                    "a concurrent run",
                    code=ErrorCode.CONCURRENT_RUN,
                    context={"plan_version_id": command.plan_version_id},
                )
            uow3.dispatches.enqueue(run_id)
            uow3.commit()
        except Exception:
            uow3.rollback()
            raise
        finally:
            uow3.close()

        if command.sync:
            from cardre.application.runs.execute_run import ExecuteRunCommand
            self._execute_run(ExecuteRunCommand(run_id=run_id))
        else:
            try:
                self._dispatcher.dispatch(RunRequest(
                    run_id=run_id,
                    plan_version_id=command.plan_version_id,
                    project_id=self._project_id,
                ))
            except Exception:
                from cardre.application.runs.finalize_run import FinalizeDiagnostic
                self._finalize_run(run_id, "failed", diagnostic=FinalizeDiagnostic(
                    code="RUN_DISPATCH_FAILED",
                    message="Failed to dispatch run",
                ))

        # Reload run to return actual status after sync execution or dispatch failure
        uow4 = self._uow_factory()
        try:
            final_run = uow4.runs.get(run_id)
            actual_status = final_run.status if final_run is not None else "submitted"
        finally:
            uow4.close()
        return SubmitRunResult(run_id=run_id, status=actual_status)

    @staticmethod
    def _validate_command(command: SubmitRunCommand):
        from cardre.domain.errors import CardreError, ErrorCode
        from cardre.domain.run import RunScope

        try:
            scope = RunScope(command.run_scope)
        except ValueError:
            raise CardreError(
                f"Invalid run_scope {command.run_scope!r}; expected one of "
                f"{[s.value for s in RunScope]}",
                code=ErrorCode.RUN_SCOPE_INVALID,
                context={"run_scope": command.run_scope},
            ) from None
        return scope

    def _sweep_stale(self) -> None:
        from datetime import UTC, datetime

        from cardre.domain.run import RunStatus

        now_ts = datetime.now(UTC).timestamp()

        # Identify runs the worker has abandoned: heartbeat absent, malformed,
        # or older than the stale window. For each, hand the *observed* heartbeat
        # value to FinalizeRun, which atomically compare-and-sets the terminal
        # transition, appends the RUN_STALE diagnostic, builds the manifest, and
        # enqueues its outbox record — all in one transaction.
        stale_candidates: list[tuple[str, str | None]] = []
        uow = self._uow_factory()
        try:
            for run in uow.runs.list_for_plan_version():
                if run.status != RunStatus.RUNNING.value:
                    continue
                if run.is_stale(
                    stale_heartbeat_seconds=self._stale_heartbeat_seconds,
                    now_ts=now_ts,
                ):
                    stale_candidates.append((run.run_id, run.heartbeat_at))
        finally:
            uow.close()

        from cardre.application.runs.finalize_run import FinalizeDiagnostic

        for run_id, hb in stale_candidates:
            # FinalizeRun performs the compare-and-set transition, diagnostic,
            # manifest build, and outbox enqueue atomically. If the worker
            # renewed the heartbeat (or the run already terminalized) before
            # this call, the transition loses and no manifest is produced.
            self._finalize_run(
                run_id,
                "interrupted",
                diagnostic=FinalizeDiagnostic(
                    code="RUN_STALE",
                    message="Run was stale and has been interrupted",
                ),
                stale_heartbeat_at=hb,
            )
