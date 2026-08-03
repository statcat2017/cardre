"""UpdateStepParams — edit a single draft step's parameters."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError, ErrorCode


@dataclass
class UpdateStepParamsCommand:
    plan_version_id: str
    step_id: str
    params: dict[str, Any]


class UpdateStepParams:
    def __init__(self, uow_factory: Callable[[], Any]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, command: UpdateStepParamsCommand) -> None:
        uow = self._uow_factory()
        try:
            existing = uow.plans.get_version(command.plan_version_id)
            if existing is None:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} not found.",
                    code=ErrorCode.PLAN_VERSION_NOT_FOUND,
                    context={"plan_version_id": command.plan_version_id},
                    status_code=404,
                )
            if existing.is_committed:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} is already committed.",
                    code=ErrorCode.PLAN_VERSION_ALREADY_COMMITTED,
                    context={"plan_version_id": command.plan_version_id},
                    status_code=409,
                )
            params_hash = json_logical_hash(command.params)
            uow.plans.update_step_params(
                command.plan_version_id, command.step_id,
                command.params, params_hash,
            )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
