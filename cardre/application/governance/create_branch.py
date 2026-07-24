"""CreateBranch — validate, remap graph, and persist a new challenger branch.

Ports ``BranchService.create_branch``, ``BranchValidator``, and
``BranchTransactionWriter`` into a single use case that owns its
own UoW for the whole operation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import BranchValidationError, GovernanceNotEnabled
from cardre.domain.plans.graph import remap_step_graph
from cardre.domain.step import StepSpec

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


@dataclass
class CreateBranchCommand:
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


@dataclass
class CreateBranchResult:
    branch_id: str
    new_plan_version_id: str
    name: str
    branch_type: str
    branch_point_step_id: str
    branch_point_canonical_step_id: str
    created_step_ids: dict[str, str]
    shared_upstream_step_ids: list[str]
    status: str = "not_run"
    warnings: list[str] = field(default_factory=list)


def _validate_segment_filter_rules(spec: dict[str, Any]) -> None:
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


class CreateBranch:
    """Validate, remap graph, and persist a new challenger branch in one UoW."""

    def __init__(self, uow_factory: Any, governance_enabled: bool = True) -> None:
        self._uow_factory = uow_factory
        self._governance_enabled = governance_enabled

    def __call__(self, command: CreateBranchCommand) -> CreateBranchResult:
        if not self._governance_enabled:
            raise GovernanceNotEnabled()

        # --- Pure validation (no I/O) ---

        bp_type = ALLOWED_BRANCH_POINTS.get(command.branch_point_step_id)
        if bp_type is None:
            raise BranchValidationError(
                code="BRANCH_POINT_NOT_ALLOWED",
                message=f"Branching from step {command.branch_point_step_id} is not supported.",
                context={"branch_point_step_id": command.branch_point_step_id},
            )
        if command.branch_type != bp_type:
            raise BranchValidationError(
                code="BRANCH_TYPE_MISMATCH",
                message=f"Branch point {command.branch_point_step_id} requires branch_type {bp_type}, got {command.branch_type}.",
                context={
                    "branch_point_step_id": command.branch_point_step_id,
                    "expected_type": bp_type,
                    "got_type": command.branch_type,
                },
            )
        if not command.name:
            raise BranchValidationError(
                code="BRANCH_NAME_REQUIRED",
                message="Branch name must not be empty.",
                context={"plan_id": command.plan_id},
            )
        if not command.created_reason:
            raise BranchValidationError(
                code="BRANCH_REASON_REQUIRED",
                message="Branch creation requires a non-empty reason.",
                context={"plan_id": command.plan_id, "name": command.name},
            )
        if command.branch_type == "segment_challenger":
            if not command.segment_filter_spec:
                raise BranchValidationError(
                    code="SEGMENT_FILTER_REQUIRED",
                    message="Segment challenger branches require a non-empty segment_filter_spec.",
                    context={"branch_type": command.branch_type},
                )
            _validate_segment_filter_rules(command.segment_filter_spec)

        # --- I/O validation + transactional write in one UoW ---

        with self._uow_factory.for_project(command.project_id) as uow:
            plan = uow.plans.get_plan(command.plan_id)
            if plan is None:
                raise BranchValidationError(
                    code="PLAN_NOT_FOUND",
                    message=f"No plan with ID {command.plan_id}",
                    context={"plan_id": command.plan_id},
                )
            pid = plan.project_id if hasattr(plan, "project_id") else plan.get("project_id")
            if pid != command.project_id:
                raise BranchValidationError(
                    code="PLAN_PROJECT_MISMATCH",
                    message=f"Plan {command.plan_id} does not belong to project {command.project_id}",
                    context={"plan_id": command.plan_id, "project_id": command.project_id},
                )

            base_branch = None
            if command.base_branch_id:
                base_branch = uow.branches.get_branch(command.base_branch_id)
                if base_branch is None:
                    raise BranchValidationError(
                        code="BASE_BRANCH_NOT_FOUND",
                        message=f"No branch with ID {command.base_branch_id}",
                        context={"base_branch_id": command.base_branch_id},
                    )

            head_pv_id = base_branch["head_plan_version_id"] if base_branch else command.base_plan_version_id

            if command.base_plan_version_id and head_pv_id != command.base_plan_version_id:
                raise BranchValidationError(
                    code="STALE_BASE_VERSION",
                    message="base_plan_version_id does not match the base branch's head_plan_version_id.",
                    context={
                        "base_plan_version_id": command.base_plan_version_id,
                        "head_pv_id": head_pv_id,
                    },
                )

            if base_branch and base_branch.get("status") != "active":
                raise BranchValidationError(
                    code="BASE_BRANCH_INACTIVE",
                    message=f"Base branch {command.base_branch_id} is not active.",
                    context={
                        "base_branch_id": command.base_branch_id,
                        "status": base_branch.get("status"),
                    },
                )

            steps = uow.plans.get_version_steps(head_pv_id)

            bp_step: StepSpec | None = None
            for s in steps:
                if s.step_id == command.branch_point_step_id or s.canonical_step_id == command.branch_point_step_id:
                    bp_step = s
                    break
            if bp_step is None:
                raise BranchValidationError(
                    code="BRANCH_POINT_NOT_IN_PLAN",
                    message=f"Step {command.branch_point_step_id} not found in plan version {head_pv_id}.",
                    context={"branch_point_step_id": command.branch_point_step_id, "head_pv_id": head_pv_id},
                )

            if command.branch_type == "reject_inference_challenger":
                sample_def_step = next(
                    (s for s in steps if s.canonical_step_id == "sample-definition"),
                    None,
                )
                if sample_def_step is None:
                    raise BranchValidationError(
                        code="REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF",
                        message="No sample-definition step found in plan. "
                                "A reject inference challenger requires a sample-definition step.",
                        context={"plan_id": command.plan_id},
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
                json.dumps(command.segment_filter_spec, sort_keys=True)
                if command.segment_filter_spec else None
            )

            # --- Graph remapping ---

            import uuid

            branch_id = f"br_{uuid.uuid4().hex[:6]}"
            clone = remap_step_graph(
                branch_id=branch_id,
                name=command.name,
                branch_point_step=bp_step,
                steps=steps,
            )

            # --- Transactional writes ---

            now = utc_now_iso()
            new_pv_id = uow.plans.create_version(
                command.plan_id,
                clone.new_steps,
                description=f"Branch '{command.name}' created from {command.branch_point_step_id}",
                is_committed=False,
            )

            conn = uow._conn  # shared connection within this transaction
            conn.execute(
                "INSERT INTO plan_branches "
                "(branch_id, project_id, plan_id, name, description, branch_type, status, "
                " base_branch_id, base_plan_version_id, head_plan_version_id, "
                " branch_point_step_id, branch_point_canonical_step_id, "
                " segment_filter_spec_json, created_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    clone.branch_id,
                    command.project_id,
                    command.plan_id,
                    command.name,
                    command.description,
                    command.branch_type,
                    command.base_branch_id,
                    head_pv_id,
                    new_pv_id,
                    command.branch_point_step_id,
                    clone.branch_point_canonical_step_id,
                    segment_filter_json,
                    command.created_reason,
                    now,
                    now,
                ),
            )

            for s in clone.new_steps:
                was_duplicated = s.step_id in clone.created_step_ids.values()
                is_shared = not was_duplicated
                original_step_id = (
                    clone.source_of_new_step.get(s.step_id) if was_duplicated
                    else s.step_id
                )

                conn.execute(
                    "INSERT INTO branch_step_map "
                    "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
                    " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        clone.branch_id,
                        new_pv_id,
                        s.canonical_step_id,
                        s.step_id,
                        command.base_branch_id if (was_duplicated or is_shared) else None,
                        original_step_id if was_duplicated else (s.step_id if is_shared else None),
                        1 if is_shared else 0,
                        0 if is_shared else 1,
                        now,
                    ),
                )

            uow.commit()

        return CreateBranchResult(
            branch_id=clone.branch_id,
            new_plan_version_id=new_pv_id,
            name=command.name,
            branch_type=command.branch_type,
            branch_point_step_id=command.branch_point_step_id,
            branch_point_canonical_step_id=clone.branch_point_canonical_step_id,
            created_step_ids=clone.created_step_ids,
            shared_upstream_step_ids=clone.shared_upstream_step_ids,
        )
