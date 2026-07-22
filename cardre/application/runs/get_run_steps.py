"""GetRunSteps — read-only query for run steps."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class GetRunStepsCommand:
    run_id: str


class GetRunSteps:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: GetRunStepsCommand) -> list[Any]:
        uow = self._uow_factory()
        return uow.run_steps.get_for_run(command.run_id)
