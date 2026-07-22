"""ApplyManualBinningEdit — apply a manual-binning edit to a plan version."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError
from cardre.domain.step import StepSpec


@dataclass
class ApplyManualBinningEditCommand:
    plan_version_id: str
    step_id: str
    overrides: list[dict[str, Any]] = field(default_factory=list)
    reviewer_notes: str = ""
    status: str = "pending"
    affected_downstream_step_ids: list[str] = field(default_factory=list)


@dataclass
class ApplyManualBinningEditResult:
    new_plan_version_id: str
    review_id: str
    affected_step_ids: list[str] = field(default_factory=list)


class ManualBinningReviewRepo(Protocol):
    def create(
        self,
        review_id: str,
        plan_version_id: str,
        step_id: str,
        status: str,
        reviewer_notes: str,
        affected_downstream_step_ids_json: str,
        created_at: str,
        updated_at: str,
    ) -> None: ...


class ApplyManualBinningEdit:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        review_repo: ManualBinningReviewRepo,
    ) -> None:
        self._uow_factory = uow_factory
        self._review_repo = review_repo

    def __call__(self, command: ApplyManualBinningEditCommand) -> ApplyManualBinningEditResult:
        uow = self._uow_factory()
        try:
            base_pv = uow.plans.get_version(command.plan_version_id)
            if base_pv is None:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} not found.",
                    code="PLAN_VERSION_NOT_FOUND",
                    context={"plan_version_id": command.plan_version_id},
                )
            if not base_pv.is_committed:
                raise CardreError(
                    f"Plan version {command.plan_version_id!r} is not committed; "
                    "only committed plan versions are eligible for mutation.",
                    code="PLAN_VERSION_NOT_COMMITTED",
                    context={"plan_version_id": command.plan_version_id},
                )

            plan_id = base_pv.plan_id
            version_number = base_pv.version_number

            self._validate_source_evidence(uow, command.plan_version_id, command.step_id)

            base_steps = uow.plans.get_version_steps(command.plan_version_id)

            mb_step = None
            downstream_ids: list[str] = []
            for step in base_steps:
                if step.step_id == command.step_id:
                    mb_step = step
                elif command.step_id in step.parent_step_ids:
                    downstream_ids.append(step.step_id)

            if mb_step is None:
                raise CardreError(
                    f"Step {command.step_id!r} not found in plan version "
                    f"{command.plan_version_id!r}.",
                    code="STEP_NOT_FOUND",
                    context={"plan_version_id": command.plan_version_id, "step_id": command.step_id},
                )

            updated_params = dict(mb_step.params)
            updated_params["overrides"] = command.overrides
            updated_params["status"] = command.status
            updated_params_hash = json_logical_hash(updated_params)

            new_steps: list[StepSpec] = []
            for step in base_steps:
                if step.step_id == command.step_id:
                    new_steps.append(StepSpec(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        node_version=step.node_version,
                        category=step.category,
                        params=updated_params,
                        params_hash=updated_params_hash,
                        parent_step_ids=list(step.parent_step_ids),
                        branch_label=step.branch_label,
                        position=step.position,
                        canonical_step_id=step.canonical_step_id,
                        branch_id=step.branch_id,
                    ))
                else:
                    new_steps.append(step)

            new_pv_id = uow.plans.create_version(
                plan_id,
                new_steps,
                description=f"Manual-binning edit from version {version_number}",
                is_committed=False,
            )

            review_id = str(uuid.uuid4())
            now = utc_now_iso()
            import json
            downstream_json = json.dumps(command.affected_downstream_step_ids)
            self._review_repo.create(
                review_id=review_id,
                plan_version_id=new_pv_id,
                step_id=command.step_id,
                status=command.status,
                reviewer_notes=command.reviewer_notes,
                affected_downstream_step_ids_json=downstream_json,
                created_at=now,
                updated_at=now,
            )

            uow.commit()

            return ApplyManualBinningEditResult(
                new_plan_version_id=new_pv_id,
                review_id=review_id,
                affected_step_ids=command.affected_downstream_step_ids or downstream_ids,
            )
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()

    def _validate_source_evidence(self, uow: Any, plan_version_id: str, step_id: str) -> None:
        edges = uow.evidence.get_edges_for_plan_step(plan_version_id, step_id)
        if not edges:
            return

        for edge in edges:
            if not edge.source_run_id or not edge.source_run_step_id:
                raise CardreError(
                    f"Evidence edge {edge.evidence_edge_id!r} for step "
                    f"{step_id!r} is missing source run references.",
                    code="EVIDENCE_VALIDATION_ERROR",
                )

        for edge in edges:
            artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
            if not artifacts:
                raise CardreError(
                    f"Evidence edge {edge.evidence_edge_id!r} for step "
                    f"{step_id!r} has no evidence artifacts.",
                    code="EVIDENCE_VALIDATION_ERROR",
                )
