"""CreateCanonicalScorecardVersion — populate a plan with the launch pathway."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cardre.application.ports.node_catalogue import NodeCataloguePort
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError, ErrorCode
from cardre.domain.plans.scorecard_pathway import build_canonical_scorecard_steps
from cardre.domain.step import StepSpec


@dataclass
class CreateCanonicalScorecardVersionCommand:
    plan_id: str
    source_path: str
    # Optional overrides for the two steps users always touch first.
    # All None means "use the canonical defaults from scorecard_pathway.py".
    target_column: str | None = None
    good_values: list[str] | None = None
    bad_values: list[str] | None = None


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

            # 3. Apply optional overrides to the define-metadata step.
            if command.target_column or command.good_values or command.bad_values:
                for i, step in enumerate(steps):
                    if step.canonical_step_id == "define-metadata":
                        params = dict(step.params)
                        if command.target_column is not None:
                            params["target_column"] = command.target_column
                        if command.good_values is not None:
                            params["good_values"] = list(command.good_values)
                        if command.bad_values is not None:
                            params["bad_values"] = list(command.bad_values)
                        steps[i] = StepSpec(
                            step_id=step.step_id, node_type=step.node_type,
                            node_version=step.node_version, category=step.category,
                            params=params, params_hash=json_logical_hash(params),
                            parent_step_ids=step.parent_step_ids,
                            branch_label=step.branch_label, position=step.position,
                            canonical_step_id=step.canonical_step_id,
                            branch_id=step.branch_id,
                        )
                        break

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
