"""CancelRun — sets cancel_requested flag on a run."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.domain.errors import CardreError, ErrorCode
from cardre.domain.run import RunStatus


@dataclass
class CancelRunCommand:
    run_id: str


class CancelRun:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: CancelRunCommand) -> Any:
        uow = self._uow_factory()
        try:
            run = uow.runs.get(command.run_id)
            if run is None:
                raise CardreError(
                    f"Run {command.run_id!r} not found",
                    code=ErrorCode.RUN_NOT_FOUND,
                    context={"run_id": command.run_id},
                    status_code=404,
                )
            if run.status in (RunStatus.RUNNING, RunStatus.CREATED, RunStatus.QUEUED):
                if run.status in (RunStatus.CREATED, RunStatus.QUEUED):
                    # No work has started, so terminalize directly: the worker
                    # (if it starts) sees a terminal run and exits before
                    # validation, and the run stops blocking submissions.
                    transitioned = uow.runs.transition(
                        command.run_id,
                        RunStatus.CANCELLED,
                        expected_from=(RunStatus.CREATED, RunStatus.QUEUED),
                    )
                    if transitioned:
                        # No worker will ever claim this run: clear its durable
                        # dispatch row so startup reconciliation does not
                        # redispatch a terminal run.
                        uow.dispatches.remove(command.run_id)
                    else:
                        # Raced the worker's claim; it is running now — fall
                        # back to cooperative cancellation.
                        uow.runs.set_cancel_requested(command.run_id)
                else:
                    uow.runs.set_cancel_requested(command.run_id)
            else:
                raise CardreError(
                    f"Run {command.run_id!r} is not running (status={run.status})",
                    code=ErrorCode.RUN_NOT_RUNNING,
                    context={"run_id": command.run_id, "status": run.status},
                    status_code=409,
                )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
        return run
