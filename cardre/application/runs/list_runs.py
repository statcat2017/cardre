"""ListRuns — read-only query for runs by plan version."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ListRunsCommand:
    plan_version_id: str


class ListRuns:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: ListRunsCommand) -> list[Any]:
        uow = self._uow_factory()
        return uow.runs.list_for_plan_version(command.plan_version_id)
