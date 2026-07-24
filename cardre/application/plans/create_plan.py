"""CreatePlan — create a new plan."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class CreatePlanCommand:
    project_id: str
    name: str


class CreatePlan:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: CreatePlanCommand) -> Any:
        uow = self._uow_factory()
        try:
            plan_id = uow.plans.create_plan(command.project_id, command.name)
            uow.commit()
            return uow.plans.get_plan(plan_id)
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
