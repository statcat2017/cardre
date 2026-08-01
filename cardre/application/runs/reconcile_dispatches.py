"""ReconcileDispatches — redispatch runs committed before a process crash.

A run's dispatch intent is committed durably in the same transaction as run
creation. If the process exits after that commit but before the in-memory
dispatch, the run stays ``created``/``queued`` with a pending dispatch row and
blocks normal resubmission of its plan version. On startup this drains pending
rows through the dispatcher so the run either executes or (if it was
terminalized meanwhile) simply has its stale row dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    ) -> None:
        self._uow_factory = uow_factory
        self._project_registry = project_registry
        self._dispatcher = dispatcher

    def __call__(self) -> ReconcileDispatchOutcome:
        outcome = ReconcileDispatchOutcome()
        from cardre.application.ports.run_dispatcher import RunRequest
        from cardre.domain.run import RunStatus

        for project_id, root in self._project_registry.list_all().items():
            if not (Path(root) / "project.sqlite").exists():
                continue
            try:
                with self._uow_factory.read_only(project_id) as uow:
                    pending = uow.dispatches.list_pending()
            except Exception:
                continue
            for run_id in pending:
                # A run terminalized before claim (dispatch failure, validation
                # failure) must not be redispatched: clear its stale row and
                # move on. Defense in depth on top of FinalizeRun clearing the
                # row in the same transaction as the terminal transition.
                try:
                    with self._uow_factory.read_only(project_id) as uow:
                        run = uow.runs.get(run_id)
                except Exception:
                    continue
                if run is not None and run.status not in (
                    RunStatus.CREATED.value, RunStatus.QUEUED.value,
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
