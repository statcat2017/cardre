"""UpdatePlanVersion — update a plan version's description."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class UpdatePlanVersionCommand:
    plan_version_id: str
    description: str


class UpdatePlanVersion:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: UpdatePlanVersionCommand) -> None:
        uow = self._uow_factory()
        try:
            uow.plans.update_version_description(
                command.plan_version_id, command.description,
            )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
