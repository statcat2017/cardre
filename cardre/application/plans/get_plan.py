"""GetPlan — get a plan by ID."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class GetPlanCommand:
    plan_id: str


class GetPlan:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: GetPlanCommand) -> Any:
        uow = self._uow_factory()
        try:
            return uow.plans.get_plan(command.plan_id)
        finally:
            uow.close()
