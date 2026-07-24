"""ListPlanVersions — list versions of a plan."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ListPlanVersionsCommand:
    plan_id: str


class ListPlanVersions:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: ListPlanVersionsCommand) -> Any:
        uow = self._uow_factory()
        try:
            return uow.plans.list_versions(command.plan_id)
        finally:
            uow.close()
