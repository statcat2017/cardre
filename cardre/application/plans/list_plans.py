"""ListPlans — list plans for a project."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ListPlansCommand:
    project_id: str


class ListPlans:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: ListPlansCommand) -> Any:
        uow = self._uow_factory()
        try:
            return uow.plans.list_for_project(command.project_id)
        finally:
            uow.close()
