"""CommitPlanVersion — commit a draft plan version."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.application.execution.topology import validate_topology
from cardre.domain.errors import CardreError


@dataclass
class CommitPlanVersionCommand:
    plan_version_id: str


class CommitPlanVersion:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: CommitPlanVersionCommand) -> Any:
        uow = self._uow_factory()
        try:
            existing = uow.plans.get_version(command.plan_version_id)
            if existing is None:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} not found.",
                    code="PLAN_VERSION_NOT_FOUND",
                    context={"plan_version_id": command.plan_version_id},
                )
            if existing.is_committed:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} is already committed.",
                    code="PLAN_VERSION_ALREADY_COMMITTED",
                    context={"plan_version_id": command.plan_version_id},
                )

            steps = uow.plans.get_version_steps(command.plan_version_id)
            validate_topology(steps)

            uow.plans.commit_version(command.plan_version_id)
            uow.commit()

            committed = uow.plans.get_version(command.plan_version_id)
            if committed is None:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} not found after commit.",
                    code="PLAN_VERSION_NOT_FOUND",
                    context={"plan_version_id": command.plan_version_id},
                )
            return committed
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
