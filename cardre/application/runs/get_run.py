"""GetRun — read-only query for a single run."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class GetRunCommand:
    run_id: str


class GetRun:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: GetRunCommand) -> Any:
        uow = self._uow_factory()
        return uow.runs.get(command.run_id)
