"""SubmitRun — validate, create, and dispatch a new run."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.application.ports.run_dispatcher import RunDispatcherPort, RunRequest


@dataclass
class SubmitRunCommand:
    plan_version_id: str
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
    ) -> None:
        self._uow_factory = uow_factory
        self._dispatcher = dispatcher
        self._execute_run = execute_run
        self._finalize_run = finalize_run

    def __call__(self, command: SubmitRunCommand) -> SubmitRunResult:
        uow = self._uow_factory()
        try:
            pv = uow.plans.get_version(command.plan_version_id)
        finally:
            uow.close()

        if pv is None:
            from cardre.domain.errors import CardreError
            raise CardreError(f"Plan version {command.plan_version_id!r} not found")
        if not getattr(pv, "is_committed", False):
            from cardre.domain.errors import CardreError
            raise CardreError(f"Plan version {command.plan_version_id!r} is not committed")

        self._sweep_stale()

        uow2 = self._uow_factory()
        try:
            existing = uow2.runs.list_for_plan_version(command.plan_version_id)
        finally:
            uow2.close()

        active_statuses = {"created", "queued", "running"}
        for run in existing:
            if run.status in active_statuses:
                from cardre.domain.errors import CardreError
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} already has "
                    f"a concurrent run in status {run.status}"
                )

        uow3 = self._uow_factory()
        try:
            run_id = uow3.runs.create(command.plan_version_id)
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
                self._dispatcher.dispatch(RunRequest(run_id=run_id, plan_version_id=command.plan_version_id))
            except Exception:
                from cardre.application.runs.finalize_run import FinalizeDiagnostic
                self._finalize_run(run_id, "failed", diagnostic=FinalizeDiagnostic(
                    code="RUN_DISPATCH_FAILED",
                    message="Failed to dispatch run",
                ))

        return SubmitRunResult(run_id=run_id, status="created")

    def _sweep_stale(self) -> None:
        from datetime import UTC, datetime

        uow = self._uow_factory()
        try:
            all_active = uow.runs.list_for_plan_version()
        finally:
            uow.close()

        from cardre.domain.run import RunStatus
        for run in all_active:
            if run.status != RunStatus.RUNNING.value:
                continue
            hb = run.heartbeat_at if hasattr(run, "heartbeat_at") else None
            is_stale = False
            if hb is None:
                is_stale = True
            else:
                try:
                    hb_ts = datetime.fromisoformat(hb).replace(tzinfo=UTC).timestamp()
                    now_ts = datetime.now(UTC).timestamp()
                    stale_seconds = 300
                    is_stale = (now_ts - hb_ts) > stale_seconds
                except (ValueError, TypeError):
                    is_stale = True
            if is_stale:
                from cardre.application.runs.finalize_run import FinalizeDiagnostic
                self._finalize_run(
                    run.run_id,
                    "interrupted",
                    diagnostic=FinalizeDiagnostic(
                        code="RUN_STALE",
                        message="Run was stale and has been interrupted",
                    ),
                )
