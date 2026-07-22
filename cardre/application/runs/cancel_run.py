"""CancelRun — sets cancel_requested flag on a run."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class CancelRunCommand:
    run_id: str


class CancelRun:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: CancelRunCommand) -> Any:
        uow = self._uow_factory()
        run = uow.runs.get(command.run_id)
        if run is None:
            from cardre.domain.errors import CardreError
            raise CardreError(f"Run {command.run_id!r} not found")
        uow.runs.set_cancel_requested(command.run_id)
        uow.commit()
        return run
