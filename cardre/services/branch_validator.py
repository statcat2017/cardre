"""Branch creation validation — pure, no database writes.

Validates branch-point allow-list, branch-type binding, name/reason
presence, segment-filter rules, plan existence and project scoping,
base-branch existence/status, branch-point step presence in the plan
version, and reject-inference domain rules.

Returns typed validated data consumed by the graph remapper and
transaction writer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from cardre.domain.errors import BranchValidationError
from cardre.domain.step import StepSpec
from cardre.store.branch_repo import BranchRepository
from cardre.store.plan_repo import PlanRepository

if TYPE_CHECKING:
    from cardre.domain.diagnostics import JsonDict
    from cardre.store.db import ProjectStore


ALLOWED_BRANCH_POINTS: dict[str, str] = {
    "sample-definition": "segment_challenger",
    "variable-selection": "variable_selection_challenger",
    "manual-binning": "binning_challenger",
    "logistic-regression": "model_challenger",
    "score-scaling": "score_scaling_challenger",
    "cutoff-analysis": "cutoff_strategy_challenger",
    "define-reject-population": "reject_inference_challenger",
}

SUPPORTED_FILTER_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "in", "not_in", "is_null", "is_not_null"}


@dataclass(frozen=True)
class ValidatedBranchData:
    """Typed output of branch validation.

    All checks have passed.  Data is ready for graph remapping and
    transactional writing.
    """
    project_id: str
    plan_id: str
    name: str
    branch_type: str
    branch_point_step_id: str
    base_branch_id: str | None = None
    base_plan_version_id: str | None = None
    created_reason: str = ""
    description: str | None = None
    segment_filter_spec: dict[str, Any] | None = None
    # Resolved during validation
    plan: JsonDict = field(default_factory=dict)
    base_branch: JsonDict | None = None
    head_pv_id: str | None = None
    bp_step: StepSpec | None = None
    steps: list[StepSpec] = field(default_factory=list)
    segment_filter_json: str | None = None


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
                message=f"'{operator}' is not supported. "
                        f"Allowed: {sorted(SUPPORTED_FILTER_OPERATORS)}",
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


class BranchValidator:
    """Pure validation for branch creation.

    Performs no database writes.  Returns ``ValidatedBranchData`` with
    resolved data consumed by the graph remapper and transaction writer.
    """

    def __init__(self, store: ProjectStore) -> None:
        self._branches = BranchRepository(store)
        self._plans = PlanRepository(store)

    def validate_create_branch(
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
    ) -> ValidatedBranchData:
        """Validate branch creation and return typed validated data."""

        # Branch-point allow-list
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
                message=f"Branch point {branch_point_step_id} requires branch_type "
                        f"{expected_type}, got {branch_type}.",
                context={
                    "branch_point_step_id": branch_point_step_id,
                    "expected_type": expected_type,
                    "got_type": branch_type,
                },
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
                context={
                    "base_plan_version_id": base_plan_version_id,
                    "head_pv_id": head_pv_id,
                },
            )

        if base_branch and base_branch.get("status") != "active":
            raise BranchValidationError(
                code="BASE_BRANCH_INACTIVE",
                message=f"Base branch {base_branch_id} is not active.",
                context={
                    "base_branch_id": base_branch_id,
                    "status": base_branch.get("status"),
                },
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

        # Reject-inference domain rules
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

        segment_filter_json = (
            json.dumps(segment_filter_spec, sort_keys=True)
            if segment_filter_spec else None
        )

        return ValidatedBranchData(
            project_id=project_id,
            plan_id=plan_id,
            name=name,
            branch_type=branch_type,
            branch_point_step_id=branch_point_step_id,
            base_branch_id=base_branch_id,
            base_plan_version_id=base_plan_version_id,
            created_reason=created_reason,
            description=description,
            segment_filter_spec=segment_filter_spec,
            plan=plan,
            base_branch=base_branch,
            head_pv_id=head_pv_id,
            bp_step=bp_step,
            steps=steps,
            segment_filter_json=segment_filter_json,
        )

__all__ = [
    "ALLOWED_BRANCH_POINTS",
    "BranchValidator",
    "SUPPORTED_FILTER_OPERATORS",
    "ValidatedBranchData",
    "_validate_segment_filter_rules",
]
