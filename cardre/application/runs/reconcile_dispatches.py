"""ReconcileDispatches — redispatch runs committed before a process crash.

A run's dispatch intent is committed durably in the same transaction as run
creation. If the process exits after that commit but before the in-memory
dispatch, the run stays ``submitted`` with a pending dispatch row and
blocks normal resubmission of its plan version. On startup this drains pending
rows through the dispatcher so the run either executes or (if it was
terminalized meanwhile) simply has its stale row dropped.

A per-Project pending-read failure is recorded as an ``error`` outcome rather
than silently skipped, and reconciliation continues to the remaining Projects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cardre.application.ports.capability_probe import CapabilityProbePort

logger = logging.getLogger(__name__)


@dataclass
class ReconcileDispatchResult:
    run_id: str
    project_id: str
    state: str  # 'dispatched' | 'skipped' | 'error'
    error: str = ""


@dataclass
class ReconcileDispatchOutcome:
    results: list[ReconcileDispatchResult] = field(default_factory=list)

    @property
    def dispatched(self) -> int:
        return sum(1 for r in self.results if r.state == "dispatched")


class ReconcileDispatches:
    def __init__(
        self,
        uow_factory: Any,
        project_registry: Any,
        dispatcher: Any,
        capability_probe: CapabilityProbePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._project_registry = project_registry
        self._dispatcher = dispatcher
        self._capability_probe = capability_probe

    def __call__(self) -> ReconcileDispatchOutcome:
        outcome = ReconcileDispatchOutcome()
        from cardre.application.ports.run_dispatcher import RunRequest
        from cardre.domain.run import RunStatus

        for project_id, root in self._project_registry.list_all().items():
            if not self._capability_probe.project_root_exists(root):
                continue
            try:
                with self._uow_factory.read_only(project_id) as uow:
                    pending = uow.dispatches.list_pending()
            except Exception as exc:
                outcome.results.append(ReconcileDispatchResult(
                    run_id="", project_id=project_id, state="error",
                    error=f"pending dispatch read failed: {exc}",
                ))
                logger.exception(
                    "ReconcileDispatches: pending dispatch read failed for "
                    "project %s; skipping it for this pass", project_id,
                )
                continue
            for run_id in pending:
                # A run terminalized before claim (dispatch failure, validation
                # failure) must not be redispatched: clear its stale row and
                # move on. Defense in depth on top of FinalizeRun clearing the
                # row in the same transaction as the terminal transition.
                try:
                    with self._uow_factory.read_only(project_id) as uow:
                        run = uow.runs.get(run_id)
                except Exception as exc:
                    outcome.results.append(ReconcileDispatchResult(
                        run_id=run_id, project_id=project_id, state="error",
                        error=f"run read failed: {exc}",
                    ))
                    logger.exception(
                        "ReconcileDispatches: run read failed for run %s in "
                        "project %s", run_id, project_id,
                    )
                    continue
                if run is not None and run.status not in (
                    RunStatus.SUBMITTED.value,
                ):
                    with self._uow_factory.for_project(project_id) as uow:
                        uow.dispatches.remove(run_id)
                        uow.commit()
                    outcome.results.append(ReconcileDispatchResult(
                        run_id=run_id, project_id=project_id, state="skipped",
                        error="run is terminal; stale dispatch row removed",
                    ))
                    continue
                try:
                    self._dispatcher.dispatch(RunRequest(
                        run_id=run_id,
                        plan_version_id="",
                        project_id=project_id,
                    ))
                    outcome.results.append(ReconcileDispatchResult(
                        run_id=run_id, project_id=project_id, state="dispatched",
                    ))
                except Exception as exc:
                    outcome.results.append(ReconcileDispatchResult(
                        run_id=run_id, project_id=project_id, state="skipped",
                        error=str(exc),
                    ))
        return outcome
