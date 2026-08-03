"""UpdateStepParams — edit draft step parameters, propagating target atomically.

The full supplied parameter set is validated against the resolved node
(schema normalization + node-level ``validate_params``) before it is
persisted. Invalid values leave the version as a draft and raise a
structured ``PARAMETER_VALIDATION_ERROR`` carrying the step and field
errors.

A target-column change on any target-dependent canonical step
(``define-metadata``, ``validate-target``, ``split``) is propagated to all
three in the same transaction, so the pathway never commits with a target
that only reaches some steps.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.application.plans.param_validation import validate_step_params
from cardre.application.ports.node_catalogue import NodeCataloguePort
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError, ErrorCode
from cardre.domain.plans.scorecard_pathway import TARGET_DEPENDENT_STEP_IDS


@dataclass
class UpdateStepParamsCommand:
    plan_version_id: str
    step_id: str
    params: dict[str, Any]


class UpdateStepParams:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        node_catalogue: NodeCataloguePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._node_catalogue = node_catalogue

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

            steps = uow.plans.get_version_steps(command.plan_version_id)
            step = next((s for s in steps if s.step_id == command.step_id), None)
            if step is None:
                raise CardreError(
                    f"Step {command.step_id!r} not found on plan version "
                    f"{command.plan_version_id!r}.",
                    code=ErrorCode.STEP_NOT_FOUND,
                    context={"plan_version_id": command.plan_version_id, "step_id": command.step_id},
                    status_code=404,
                )

            node_cls = self._node_catalogue.resolve(step.node_type)
            normalized, errors = validate_step_params(node_cls, command.params)
            if errors:
                raise CardreError(
                    f"Step {command.step_id!r} parameters are invalid.",
                    code=ErrorCode.PARAMETER_VALIDATION_ERROR,
                    context={"step_id": command.step_id, "errors": errors},
                    status_code=422,
                )

            # Atomic target propagation: a target-column edit on any
            # target-dependent canonical step must reach all of them, or the
            # pathway would validate/split on a different column than it
            # defines.
            target_column = normalized.get("target_column")
            is_target_dependent = step.canonical_step_id in TARGET_DEPENDENT_STEP_IDS
            if target_column is not None and is_target_dependent:
                updates: dict[str, dict[str, Any]] = {command.step_id: normalized}
                for other in steps:
                    if (
                        other.step_id != command.step_id
                        and other.canonical_step_id in TARGET_DEPENDENT_STEP_IDS
                    ):
                        merged = dict(other.params)
                        merged["target_column"] = target_column
                        other_cls = self._node_catalogue.resolve(other.node_type)
                        _, other_errors = validate_step_params(other_cls, merged)
                        if other_errors:
                            raise CardreError(
                                f"Step {other.step_id!r} parameters are invalid after target propagation.",
                                code=ErrorCode.PARAMETER_VALIDATION_ERROR,
                                context={"step_id": other.step_id, "errors": other_errors},
                                status_code=422,
                            )
                        updates[other.step_id] = merged

                for step_id, params in updates.items():
                    uow.plans.update_step_params(
                        command.plan_version_id, step_id,
                        params, json_logical_hash(params),
                    )
            else:
                uow.plans.update_step_params(
                    command.plan_version_id, command.step_id,
                    normalized, json_logical_hash(normalized),
                )
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
