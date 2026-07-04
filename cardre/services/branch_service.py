"""BranchService — branch creation and management logic.

Port from v1, repointed to v2 infrastructure (evidence_edges/evidence_artifacts
for branch evidence, plan_step_edges for DAG).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import BranchValidationError
from cardre.domain.step import StepSpec
from cardre.execution.step_graph import descendant_closure
from cardre.store.branch_repo import BranchRepository
from cardre.store.db import ProjectStore
from cardre.store.plan_repo import PlanRepository

ALLOWED_BRANCH_POINTS: dict[str, str] = {
    "sample-definition": "segment_challenger",
    "variable-selection": "variable_selection_challenger",
    "manual-binning": "binning_challenger",
    "logistic-regression": "model_challenger",
    "score-scaling": "score_scaling_challenger",
    "cutoff-analysis": "cutoff_strategy_challenger",
    "define-reject-population": "reject_inference_challenger",
}


class BranchService:
    """Business logic for branch creation and management."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store
        self._branches = BranchRepository(store)
        self._plans = PlanRepository(store)

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
            raise BranchValidationError(
                code="BRANCH_POINT_NOT_ALLOWED",
                message=f"Branching from step {branch_point_step_id} is not supported.",
                context={"branch_point_step_id": branch_point_step_id},
            )

        expected_type = ALLOWED_BRANCH_POINTS[branch_point_step_id]
        if branch_type != expected_type:
            raise BranchValidationError(
                code="BRANCH_TYPE_MISMATCH",
                message=f"Branch point {branch_point_step_id} requires branch_type {expected_type}, got {branch_type}.",
                context={"branch_point_step_id": branch_point_step_id, "expected_type": expected_type, "got_type": branch_type},
            )

        if not name:
            raise BranchValidationError(
                code="BRANCH_NAME_REQUIRED",
                message="Branch name must not be empty.",
                context={"plan_id": plan_id},
            )

        if not created_reason:
            raise BranchValidationError(
                code="BRANCH_REASON_REQUIRED",
                message="Branch creation requires a non-empty reason.",
                context={"plan_id": plan_id, "name": name},
            )

        if branch_type == "segment_challenger":
            if not segment_filter_spec:
                raise BranchValidationError(
                    code="SEGMENT_FILTER_REQUIRED",
                    message="Segment challenger branches require a non-empty segment_filter_spec.",
                    context={"branch_type": branch_type},
                )
            _validate_segment_filter_rules(segment_filter_spec)

        # Validate plan belongs to project
        plan = self._plans.get_plan(plan_id)
        if plan is None:
            raise BranchValidationError(
                code="PLAN_NOT_FOUND",
                message=f"No plan with ID {plan_id}",
                context={"plan_id": plan_id},
            )
        if plan.get("project_id") != project_id:
            raise BranchValidationError(
                code="PLAN_PROJECT_MISMATCH",
                message=f"Plan {plan_id} does not belong to project {project_id}",
                context={"plan_id": plan_id, "project_id": project_id},
            )

        # Load base branch
        base_branch = self._branches.get_branch(base_branch_id) if base_branch_id else None
        if base_branch_id and base_branch is None:
            raise BranchValidationError(
                code="BASE_BRANCH_NOT_FOUND",
                message=f"No branch with ID {base_branch_id}",
                context={"base_branch_id": base_branch_id},
            )

        head_pv_id = base_branch["head_plan_version_id"] if base_branch else base_plan_version_id

        if base_plan_version_id and head_pv_id != base_plan_version_id:
            raise BranchValidationError(
                code="STALE_BASE_VERSION",
                message="base_plan_version_id does not match the base branch's head_plan_version_id.",
                context={"base_plan_version_id": base_plan_version_id, "head_pv_id": head_pv_id},
            )

        if base_branch and base_branch.get("status") != "active":
            raise BranchValidationError(
                code="BASE_BRANCH_INACTIVE",
                message=f"Base branch {base_branch_id} is not active.",
                context={"base_branch_id": base_branch_id, "status": base_branch.get("status")},
            )

        steps = self._plans.get_version_steps(cast("str", head_pv_id))

        bp_step = None
        for s in steps:
            if s.step_id == branch_point_step_id or s.canonical_step_id == branch_point_step_id:
                bp_step = s
                break
        if bp_step is None:
            raise BranchValidationError(
                code="BRANCH_POINT_NOT_IN_PLAN",
                message=f"Step {branch_point_step_id} not found in plan version {head_pv_id}.",
                context={"branch_point_step_id": branch_point_step_id, "head_pv_id": head_pv_id},
            )

        if branch_type == "reject_inference_challenger":
            sample_def_step = next(
                (s for s in steps if s.canonical_step_id == "sample-definition"),
                None,
            )
            if sample_def_step is None:
                raise BranchValidationError(
                    code="REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF",
                    message="No sample-definition step found in plan. "
                    "A reject inference challenger requires a sample-definition step.",
                    context={"plan_id": plan_id},
                )
            sample_domain = sample_def_step.params.get("sample_domain", "ttd")
            if sample_domain != "ttd":
                raise BranchValidationError(
                    code="REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD",
                    message=f"sample_domain must be 'ttd', got {sample_domain!r}. "
                    "Cannot add reject inference to an OTB sample.",
                    context={"sample_domain": sample_domain},
                )

        # --- Generate branch ID and step IDs ---

        branch_id = f"br_{uuid.uuid4().hex[:6]}"
        dup_closure = descendant_closure(bp_step.step_id, steps)

        # Build step_id mapping: original -> generated (for duplicated steps)
        step_id_map: dict[str, str] = {}
        for s in steps:
            if s.step_id in dup_closure:
                new_step_id = f"{s.canonical_step_id}__{branch_id}"
                step_id_map[s.step_id] = new_step_id
            else:
                step_id_map[s.step_id] = s.step_id

        created_step_ids: dict[str, str] = {}
        shared_upstream_step_ids: list[str] = []

        new_steps: list[StepSpec] = []
        source_of_new_step: dict[str, str] = {}

        for s in steps:
            if s.step_id in dup_closure:
                new_step_id = step_id_map[s.step_id]
                source_of_new_step[new_step_id] = s.step_id

                remapped_parents = [
                    step_id_map.get(pid, pid)
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

        with self._store.transaction() as conn:
            # Insert plan version + steps via the shared plan repository.
            new_pv_id = self._plans.create_version(
                plan_id,
                new_steps,
                description=f"Branch '{name}' created from {branch_point_step_id}",
                is_committed=False,
                conn=conn,
            )

            # Insert branch metadata
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

            # Insert step maps
            for s in new_steps:
                was_duplicated = s.step_id in list(created_step_ids.values())
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


def _validate_segment_filter_rules(spec: dict[str, Any]) -> None:
    """Validate segment filter rules match the ApplyExclusions operator contract."""
    rules = spec.get("rules", [])
    if not rules:
        raise BranchValidationError(
            code="SEGMENT_FILTER_RULES_REQUIRED",
            message="Segment filter must have at least one rule.",
        )

    for rule in rules:
        column = rule.get("column", "")
        operator = rule.get("operator", "")
        reason = rule.get("reason", "")
        value = rule.get("value")

        if not column:
            raise BranchValidationError(
                code="SEGMENT_FILTER_INVALID",
                message="Rule must specify a non-empty 'column'.",
                context={"column": column},
            )
        if not operator:
            raise BranchValidationError(
                code="SEGMENT_FILTER_INVALID",
                message="Rule must specify an 'operator'.",
                context={"column": column},
            )
        if operator not in SUPPORTED_FILTER_OPERATORS:
            raise BranchValidationError(
                code="SEGMENT_FILTER_UNSUPPORTED_OPERATOR",
                message=f"'{operator}' is not supported. Allowed: {sorted(SUPPORTED_FILTER_OPERATORS)}",
                context={"operator": operator, "column": column},
            )
        if not reason:
            raise BranchValidationError(
                code="SEGMENT_FILTER_REASON_REQUIRED",
                message=f"Rule for column '{column}' requires a non-empty 'reason'.",
                context={"column": column},
            )
        if operator not in ("is_null", "is_not_null") and value is None:
            raise BranchValidationError(
                code="SEGMENT_FILTER_VALUE_REQUIRED",
                message=f"Rule for column '{column}' with operator '{operator}' requires a 'value'.",
                context={"column": column, "operator": operator},
            )
