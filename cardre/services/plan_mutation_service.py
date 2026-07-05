"""PlanMutationService — atomic mutations on plan graphs.

The service creates new draft plan versions (never mutates committed
versions) and persists side-effect rows (reviews, annotations) in the
same transaction as the new plan version + steps.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError
from cardre.domain.step import StepSpec
from cardre.store.manual_binning_repo import ManualBinningRepository
from cardre.store.plan_repo import PlanRepository

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


@dataclass(frozen=True)
class ManualBinningEditCommand:
    """Command payload for applying a manual-binning edit.

    Attributes:
        plan_version_id: Base plan version to fork from (must be committed).
        step_id: The manual-binning step to update within the plan.
        overrides: List of bin override dicts to set on the step params.
        reviewer_notes: Optional notes from the reviewer.
        status: Review status (pending | approved | rejected).
        affected_downstream_step_ids: UI hint for which steps are affected.
    """
    plan_version_id: str
    step_id: str
    overrides: list[dict[str, Any]] = field(default_factory=list)
    reviewer_notes: str = ""
    status: str = "pending"
    affected_downstream_step_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ManualBinningEditResult:
    """Result of a successful manual-binning edit.

    Attributes:
        new_plan_version_id: The newly created draft plan version ID.
        review_id: The persisted review ID.
        affected_step_ids: List of step IDs affected downstream.
    """
    new_plan_version_id: str
    review_id: str
    affected_step_ids: list[str] = field(default_factory=list)


class PlanMutationError(CardreError):
    """Raised when a plan mutation is rejected."""
    code = "PLAN_MUTATION_ERROR"
    status_code = 400


class PlanMutationService:
    """Service for atomic plan mutations that create new draft versions."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._review_repo = ManualBinningRepository(store)

    def apply_manual_binning_edit(
        self,
        command: ManualBinningEditCommand,
    ) -> ManualBinningEditResult:
        """Apply a manual-binning edit and return the new draft version + review.

        All mutations happen in a single transaction. Historical evidence
        rows are never modified.
        """
        # 1. Validate the base plan version exists and is committed
        base_pv = self._store.execute(
            "SELECT * FROM plan_versions WHERE plan_version_id = ?",
            (command.plan_version_id,),
        ).fetchone()
        if base_pv is None:
            raise PlanMutationError(
                f"Plan version {command.plan_version_id!r} not found."
            )
        base_pv = dict(base_pv)
        if not base_pv.get("is_committed"):
            raise PlanMutationError(
                f"Plan version {command.plan_version_id!r} is not committed; "
                "only committed plan versions are eligible for mutation."
            )

        plan_id = base_pv["plan_id"]
        version_number = base_pv["version_number"]

        # 2. Validate that the source fine-classing step has evidence
        #    (reads from evidence_edges + evidence_artifacts)
        #    Since execution may not exist yet, this validation is best-effort.
        self._validate_source_evidence(command.plan_version_id, command.step_id)

        # 3. Retrieve the existing steps and edges from the base version
        base_steps = self._get_version_steps(command.plan_version_id)
        # Find the manual-binning step and downstream steps
        mb_step = None
        downstream_ids: list[str] = []
        for step in base_steps:
            if step.step_id == command.step_id:
                mb_step = step
            elif command.step_id in step.parent_step_ids:
                downstream_ids.append(step.step_id)

        if mb_step is None:
            raise PlanMutationError(
                f"Step {command.step_id!r} not found in plan version "
                f"{command.plan_version_id!r}."
            )

        # 4. Create the updated step params (merge overrides)
        updated_params = dict(mb_step.params)
        updated_params["overrides"] = command.overrides
        updated_params["status"] = command.status

        from cardre.domain.artifacts import json_logical_hash
        updated_params_hash = json_logical_hash(updated_params)

        # 5. Build the new step list with the updated manual-binning step
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

        # 6. Execute all mutations in a single transaction
        with self._store.transaction("IMMEDIATE") as conn:
            now = utc_now_iso()
            # 6a. Create the new draft plan version + steps via the shared plan repository.
            new_pv_id = PlanRepository(self._store).create_version(
                plan_id,
                new_steps,
                description=f"Manual-binning edit from version {version_number}",
                is_committed=False,
                conn=conn,
            )

            # 6b. Persist ManualBinningReview row
            review_id = str(uuid.uuid4())
            downstream_json = json.dumps(command.affected_downstream_step_ids)
            conn.execute(
                "INSERT INTO manual_binning_reviews "
                "(review_id, plan_version_id, step_id, status, reviewer_notes, "
                " affected_downstream_step_ids_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (review_id, new_pv_id, command.step_id, command.status,
                 command.reviewer_notes, downstream_json, now, now),
            )

        return ManualBinningEditResult(
            new_plan_version_id=new_pv_id,
            review_id=review_id,
            affected_step_ids=command.affected_downstream_step_ids or downstream_ids,
        )

    def _validate_source_evidence(
        self,
        plan_version_id: str,
        step_id: str,
    ) -> None:
        """Validate that source fine-classing evidence exists for the step.

        Since execution may not be available yet, this is best-effort:
        if there are evidence_edges rows for this step, they must have
        valid source references.
        """
        edges = self._store.execute(
            "SELECT ee.* FROM evidence_edges ee "
            "WHERE ee.plan_version_id = ? AND ee.step_id = ?",
            (plan_version_id, step_id),
        ).fetchall()

        # No evidence yet is acceptable (no execution run has happened).
        # If evidence exists, validate its structure.
        if not edges:
            return

        for edge in edges:
            edge = dict(edge)
            if not edge.get("source_run_id") or not edge.get("source_run_step_id"):
                raise PlanMutationError(
                    f"Evidence edge {edge.get('evidence_edge_id')!r} for step "
                    f"{step_id!r} is missing source run references."
                )

        # Validate evidence_artifacts are present for each edge
        for edge in edges:
            edge_dict = dict(edge)
            artifacts = self._store.execute(
                "SELECT * FROM evidence_artifacts WHERE evidence_edge_id = ?",
                (edge_dict["evidence_edge_id"],),
            ).fetchall()
            if not artifacts:
                raise PlanMutationError(
                    f"Evidence edge {edge_dict['evidence_edge_id']!r} for step "
                    f"{step_id!r} has no evidence artifacts."
                )

    def _get_version_steps(self, plan_version_id: str) -> list[StepSpec]:
        """Retrieve steps for a plan version."""
        rows = self._store.execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (plan_version_id,),
        ).fetchall()
        steps: list[StepSpec] = []
        for row in rows:
            parent_ids = [
                r["parent_step_id"]
                for r in self._store.execute(
                    "SELECT parent_step_id FROM plan_step_edges "
                    "WHERE plan_version_id = ? AND child_step_id = ? ORDER BY edge_order",
                    (plan_version_id, row["step_id"]),
                ).fetchall()
            ]
            steps.append(StepSpec(
                step_id=row["step_id"],
                node_type=row["node_type"],
                node_version=row["node_version"],
                category=row["category"],
                params=json.loads(row["params_json"]),
                params_hash=row["params_hash"],
                parent_step_ids=parent_ids,
                branch_label=row["branch_label"],
                position=row["position"],
                canonical_step_id=row["canonical_step_id"],
                branch_id=row["branch_id"],
            ))
        return steps

__all__ = [
    "ManualBinningEditCommand",
    "ManualBinningEditResult",
    "PlanMutationError",
    "PlanMutationService",
]
