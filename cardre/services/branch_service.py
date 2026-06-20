"""BranchService — branch creation and management logic.

Follows the constrained branching model from the Phase 4 technical spec.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.audit import StepSpec, utc_now_iso
from cardre.store import ProjectStore


ALLOWED_BRANCH_POINTS: dict[str, str] = {
    "sample-definition": "segment_challenger",
    "variable-selection": "variable_selection_challenger",
    "manual-binning": "binning_challenger",
    "logistic-regression": "model_challenger",
    "score-scaling": "score_scaling_challenger",
    "cutoff-analysis": "cutoff_strategy_challenger",
    "define-reject-population": "reject_inference_challenger",
}


def _descendant_closure(step_id: str, steps: list[StepSpec]) -> set[str]:
    step_ids = {s.step_id for s in steps}
    if step_id not in step_ids:
        raise KeyError(step_id)
    descendants = set()
    changed = True
    while changed:
        changed = False
        for s in steps:
            if s.step_id in descendants:
                continue
            if s.step_id == step_id or descendants.intersection(s.parent_step_ids):
                descendants.add(s.step_id)
                changed = True
    return descendants | {step_id}


class BranchService:
    """Business logic for branch creation and management."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def create_branch(
        self,
        project_id: str,
        plan_id: str,
        name: str,
        branch_type: str,
        branch_point_step_id: str,
        base_branch_id: str | None = None,
        base_plan_version_id: str | None = None,
        created_reason: str = "",
        description: str | None = None,
        segment_filter_spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a constrained challenger branch from a permitted branch point.

        Atomic: plan version, branch metadata, and branch step maps
        are committed in a single transaction.

        Returns a dict with branch metadata, created step IDs, and shared
        upstream step IDs.
        """
        # --- Validation ---

        if branch_point_step_id not in ALLOWED_BRANCH_POINTS:
            raise ValueError(
                f"BRANCH_POINT_NOT_ALLOWED: Branching from step "
                f"{branch_point_step_id} is not supported in Phase 4."
            )

        expected_type = ALLOWED_BRANCH_POINTS[branch_point_step_id]
        if branch_type != expected_type:
            raise ValueError(
                f"BRANCH_TYPE_MISMATCH: Branch point {branch_point_step_id} "
                f"requires branch_type {expected_type}, got {branch_type}."
            )

        if not name:
            raise ValueError("BRANCH_NAME_REQUIRED: Branch name must not be empty.")

        if not created_reason:
            raise ValueError("BRANCH_REASON_REQUIRED: Branch creation requires a non-empty reason.")

        if branch_type == "segment_challenger":
            if not segment_filter_spec:
                raise ValueError(
                    "SEGMENT_FILTER_REQUIRED: Segment challenger branches "
                    "require a non-empty segment_filter_spec."
                )
            _validate_segment_filter_rules(segment_filter_spec)

        # Validate plan belongs to project
        plan = self._store.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"PLAN_NOT_FOUND: No plan with ID {plan_id}")
        if plan.get("project_id") != project_id:
            raise ValueError(f"PLAN_PROJECT_MISMATCH: Plan {plan_id} does not belong to project {project_id}")

        # Load base branch
        base_branch = self._store.get_branch(base_branch_id) if base_branch_id else None
        if base_branch_id and base_branch is None:
            raise ValueError(f"BASE_BRANCH_NOT_FOUND: No branch with ID {base_branch_id}")

        head_pv_id = base_branch["head_plan_version_id"] if base_branch else base_plan_version_id

        if base_plan_version_id and head_pv_id != base_plan_version_id:
            raise ValueError(
                "STALE_BASE_VERSION: base_plan_version_id does not match "
                "the base branch's head_plan_version_id."
            )

        if base_branch and base_branch.get("status") != "active":
            raise ValueError(f"BASE_BRANCH_INACTIVE: Base branch {base_branch_id} is not active.")

        steps = self._store.get_plan_version_steps(head_pv_id)

        bp_step = None
        for s in steps:
            if s.step_id == branch_point_step_id:
                bp_step = s
                break
        if bp_step is None:
            raise ValueError(
                f"BRANCH_POINT_NOT_IN_PLAN: Step {branch_point_step_id} "
                f"not found in plan version {head_pv_id}."
            )

        if branch_type == "reject_inference_challenger":
            sample_def_step = next(
                (s for s in steps if s.canonical_step_id == "sample-definition"),
                None,
            )
            if sample_def_step is None:
                raise ValueError(
                    "REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF: "
                    "No sample-definition step found in plan. "
                    "A reject inference challenger requires a sample-definition step."
                )
            sample_domain = sample_def_step.params.get("sample_domain", "ttd")
            if sample_domain != "ttd":
                raise ValueError(
                    f"REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD: "
                    f"sample_domain must be 'ttd', got {sample_domain!r}. "
                    "Cannot add reject inference to an OTB sample."
                )

        # --- Generate branch ID and step IDs ---

        branch_id = f"br_{uuid.uuid4().hex[:6]}"
        duplicate_closure = _descendant_closure(branch_point_step_id, steps)

        # Build step_id mapping: original -> generated (for duplicated steps)
        step_id_map: dict[str, str] = {}
        for s in steps:
            if s.step_id in duplicate_closure:
                new_step_id = f"{s.canonical_step_id}__{branch_id}"
                step_id_map[s.step_id] = new_step_id
            else:
                step_id_map[s.step_id] = s.step_id

        created_step_ids: dict[str, str] = {}
        shared_upstream_step_ids: list[str] = []

        new_steps: list[StepSpec] = []
        # Remember original step_id for each new step for source_step_id
        source_of_new_step: dict[str, str] = {}

        for s in steps:
            if s.step_id in duplicate_closure:
                new_step_id = step_id_map[s.step_id]
                source_of_new_step[new_step_id] = s.step_id

                remapped_parents = [
                    step_id_map[pid] if pid in step_id_map else pid
                    for pid in s.parent_step_ids
                ]

                new_spec = StepSpec(
                    step_id=new_step_id,
                    node_type=s.node_type,
                    node_version=s.node_version,
                    category=s.category,
                    params=dict(s.params),
                    params_hash=s.params_hash,
                    parent_step_ids=remapped_parents,
                    branch_label=name,
                    position=s.position,
                    canonical_step_id=s.canonical_step_id,
                    branch_id=branch_id,
                )
                new_steps.append(new_spec)
                created_step_ids[s.canonical_step_id] = new_step_id
            else:
                new_steps.append(s)
                shared_upstream_step_ids.append(s.step_id)

        # --- Atomic creation: plan version + branch metadata + step maps ---

        now = utc_now_iso()
        segment_filter_json = json.dumps(segment_filter_spec, sort_keys=True) if segment_filter_spec else None

        connection = self._store._connect()
        with self._store.transaction() as conn:
            new_pv_id = self._store.create_plan_version_in_transaction(
                conn=conn,
                plan_id=plan_id,
                steps=new_steps,
                description=f"Branch '{name}' created from {branch_point_step_id}",
            )

            conn.execute(
                "INSERT INTO plan_branches "
                "(branch_id, project_id, plan_id, name, description, branch_type, status, "
                " base_branch_id, base_plan_version_id, head_plan_version_id, "
                " branch_point_step_id, branch_point_canonical_step_id, "
                " segment_filter_spec_json, created_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    branch_id, project_id, plan_id, name, description, branch_type,
                    base_branch_id, head_pv_id, new_pv_id,
                    branch_point_step_id, bp_step.canonical_step_id,
                    segment_filter_json,
                    created_reason, now, now,
                ),
            )

            for s in new_steps:
                was_duplicated = s.step_id in [v for v in created_step_ids.values()]
                is_shared = not was_duplicated
                original_step_id = source_of_new_step.get(s.step_id) if was_duplicated else s.step_id

                conn.execute(
                    "INSERT INTO branch_step_map "
                    "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
                    " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        branch_id, new_pv_id, s.canonical_step_id, s.step_id,
                        base_branch_id if (was_duplicated or is_shared) else None,
                        original_step_id if was_duplicated else s.step_id if is_shared else None,
                        1 if is_shared else 0,
                        0 if is_shared else 1,
                        now,
                    ),
                )

        return {
            "branch_id": branch_id,
            "new_plan_version_id": new_pv_id,
            "name": name,
            "branch_type": branch_type,
            "branch_point_step_id": branch_point_step_id,
            "branch_point_canonical_step_id": bp_step.canonical_step_id,
            "created_step_ids": created_step_ids,
            "shared_upstream_step_ids": shared_upstream_step_ids,
            "status": "not_run",
            "warnings": [],
        }


SUPPORTED_FILTER_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "in", "not_in", "is_null", "is_not_null"}


def _validate_segment_filter_rules(spec: dict) -> None:
    """Validate segment filter rules match the ApplyExclusions operator contract."""
    rules = spec.get("rules", [])
    if not rules:
        raise ValueError("SEGMENT_FILTER_RULES_REQUIRED: Segment filter must have at least one rule.")

    for rule in rules:
        column = rule.get("column", "")
        operator = rule.get("operator", "")
        reason = rule.get("reason", "")
        value = rule.get("value")

        if not column:
            raise ValueError("SEGMENT_FILTER_INVALID: Rule must specify a non-empty 'column'.")
        if not operator:
            raise ValueError("SEGMENT_FILTER_INVALID: Rule must specify an 'operator'.")
        if operator not in SUPPORTED_FILTER_OPERATORS:
            raise ValueError(
                f"SEGMENT_FILTER_UNSUPPORTED_OPERATOR: '{operator}' is not supported. "
                f"Allowed: {sorted(SUPPORTED_FILTER_OPERATORS)}"
            )
        if not reason:
            raise ValueError(
                f"SEGMENT_FILTER_REASON_REQUIRED: Rule for column '{column}' "
                f"requires a non-empty 'reason'."
            )
        if operator not in ("is_null", "is_not_null") and value is None:
            raise ValueError(
                f"SEGMENT_FILTER_VALUE_REQUIRED: Rule for column '{column}' "
                f"with operator '{operator}' requires a 'value'."
            )
