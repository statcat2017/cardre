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
            # A run that has been submitted but not yet claimed by a worker
            # (created/queued) is cancellable: flag it so the worker observes
            # cancel_requested at its first fence and finalizes as cancelled
            # instead of running.
            if run.status not in (RunStatus.RUNNING, RunStatus.CREATED, RunStatus.QUEUED):
                raise CardreError(
                    f"Run {command.run_id!r} is not running (status={run.status})",
                    code=ErrorCode.RUN_NOT_RUNNING,
                    context={"run_id": command.run_id, "status": run.status},
                    status_code=409,
                )
            uow.runs.set_cancel_requested(command.run_id)
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
        return run
