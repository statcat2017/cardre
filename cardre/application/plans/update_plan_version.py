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
            existing = uow.plans.get_version(command.plan_version_id)
            if existing is None:
                from cardre.domain.errors import CardreError
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} not found.",
                    code="PLAN_VERSION_NOT_FOUND",
                    context={"plan_version_id": command.plan_version_id},
                    status_code=404,
                )
            if existing.is_committed:
                # Committed plan versions are immutable: they are the audited
                # input to executed runs. Only a new draft may be edited.
                from cardre.domain.errors import CardreError, ErrorCode
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} is already committed.",
                    code=ErrorCode.PLAN_VERSION_ALREADY_COMMITTED,
                    context={"plan_version_id": command.plan_version_id},
                    status_code=409,
                )
            uow.plans.update_version_description(
                command.plan_version_id, command.description,
            )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
