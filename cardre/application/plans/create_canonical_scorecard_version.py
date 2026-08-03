"""CreateCanonicalScorecardVersion — populate a plan with the launch pathway."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cardre.application.ports.node_catalogue import NodeCataloguePort
from cardre.domain.errors import CardreError, ErrorCode
from cardre.domain.plans.scorecard_pathway import (
    build_canonical_scorecard_steps,
    configure_canonical_scorecard,
)


@dataclass
class CreateCanonicalScorecardVersionCommand:
    plan_id: str
    source_path: str
    # Optional target configuration. All None means "use the canonical
    # defaults from scorecard_pathway.py". target_column propagates to every
    # target-dependent step (define-metadata, validate-target, split).
    target_column: str | None = None
    good_values: list[str] | None = None
    bad_values: list[str] | None = None
    # Optional business metadata for the define-metadata step. The production
    # template leaves these empty; a real project supplies them before commit.
    product: str | None = None
    segment: str | None = None
    observation_window: str | None = None
    performance_window: str | None = None
    reject_inference_position: str | None = None
    accept_automated: bool | None = None
    smoothing: dict[str, Any] | None = None


class CreateCanonicalScorecardVersion:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        node_catalogue: NodeCataloguePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._node_catalogue = node_catalogue

    def __call__(self, command: CreateCanonicalScorecardVersionCommand) -> Any:
        uow = self._uow_factory()
        try:
            # 1. Plan must exist.
            plan = uow.plans.get_plan(command.plan_id)
            if plan is None:
                raise CardreError(
                    f"Plan {command.plan_id!r} not found.",
                    code=ErrorCode.PLAN_NOT_FOUND,
                    context={"plan_id": command.plan_id},
                    status_code=404,
                )

            # 2. Build the canonical step set. build_canonical_scorecard_steps
            #    already resolves node_version/category from the catalogue
            #    and sets the import step's source_path.
            steps = build_canonical_scorecard_steps(
                Path(command.source_path),
                self._node_catalogue.resolve,
            )

            # 3. Apply optional configuration through the single canonical
            #    pathway config function, which propagates target to every
            #    target-dependent step.
            steps = configure_canonical_scorecard(
                steps,
                target_column=command.target_column,
                good_values=command.good_values,
                bad_values=command.bad_values,
                product=command.product,
                segment=command.segment,
                observation_window=command.observation_window,
                performance_window=command.performance_window,
                reject_inference_position=command.reject_inference_position,
                accept_automated=command.accept_automated,
                smoothing=command.smoothing,
            )

            # 4. Persist as a draft version. create_version already exists
            #    on PlanRepoPort and the SQLite adapter.
            pv_id = uow.plans.create_version(
                command.plan_id, steps, is_committed=False,
                description="Canonical scorecard pathway",
            )
            uow.commit()
            return uow.plans.get_version(pv_id)
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
