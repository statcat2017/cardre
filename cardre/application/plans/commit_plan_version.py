"""CommitPlanVersion — commit a draft plan version."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cardre.application.execution.topology import validate_topology
from cardre.application.plans.canonical_readiness import validate_canonical_readiness
from cardre.application.plans.param_validation import validate_step_params
from cardre.application.ports.node_catalogue import NodeCataloguePort
from cardre.domain.errors import CardreError, ErrorCode


@dataclass
class CommitPlanVersionCommand:
    plan_version_id: str


class CommitPlanVersion:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        node_catalogue: NodeCataloguePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._node_catalogue = node_catalogue

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
                    code=ErrorCode.PLAN_VERSION_ALREADY_COMMITTED,
                    context={"plan_version_id": command.plan_version_id},
                )

            steps = uow.plans.get_version_steps(command.plan_version_id)
            validate_topology(steps)

            # Defensive: validate every step's parameter set against its
            # resolved node before the version becomes immutable. A committed
            # version cannot be corrected, so a bad edit must be caught here.
            errors_by_step: list[dict[str, Any]] = []
            normalized_by_step: dict[str, dict[str, Any]] = {}
            for step in steps:
                node_cls = self._node_catalogue.resolve(step.node_type)
                normalized, errors = validate_step_params(node_cls, step.params)
                normalized_by_step[step.step_id] = normalized
                if errors:
                    errors_by_step.append({
                        "step_id": step.step_id,
                        "canonical_step_id": step.canonical_step_id,
                        "errors": errors,
                    })

            # Canonical-pathway readiness: explicit modelling decisions beyond
            # generic node validation (business metadata, target definition,
            # manual-binning outcome, consistent target) must be recorded
            # before commit. Run against the normalized parameter sets so an
            # absent/null target key cannot slip past the check.
            errors_by_step.extend(
                validate_canonical_readiness(
                    steps, normalized_params=normalized_by_step,
                )
            )

            if errors_by_step:
                raise CardreError(
                    "Plan version contains steps with invalid parameters.",
                    code=ErrorCode.PARAMETER_VALIDATION_ERROR,
                    context={"errors": errors_by_step},
                    status_code=422,
                )

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
