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

        for project_id, root in self._project_registry.list_all().items():
            if not (Path(root) / "project.sqlite").exists():
                continue
            try:
                with self._uow_factory.read_only(project_id) as uow:
                    pending = uow.dispatches.list_pending()
            except Exception:
                continue
            for run_id in pending:
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
                    # The dispatcher rejects runs it already has active, and a
                    # run may have been terminalized meanwhile (its row will be
                    # removed on claim/cancel). Neither is an error worth
                    # surfacing at startup.
                    outcome.results.append(ReconcileDispatchResult(
                        run_id=run_id, project_id=project_id, state="skipped",
                        error=str(exc),
                    ))
        return outcome
