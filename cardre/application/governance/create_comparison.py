"""CreateComparison — create a comparison intent between baseline and challenger branches.

Ports ``comparison_service.create_comparison`` into a single use case
that owns its own UoW.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from cardre.application.ports.id_generator import IdGeneratorPort
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError, GovernanceNotEnabled

DEFAULT_COMPARISON_SPEC: dict[str, Any] = {
    "roles": ["train", "test", "oot"],
    "include_woe_iv": True,
    "include_model": True,
    "include_validation": True,
    "include_cutoff": True,
    "include_warnings": True,
}


@dataclass
class CreateComparisonCommand:
    project_id: str
    plan_id: str
    baseline_branch_id: str
    challenger_branch_ids: list[str]
    comparison_spec: dict[str, Any] | None = None
    created_reason: str | None = None


@dataclass
class CreateComparisonResult:
    comparison_id: str
    project_id: str
    plan_id: str
    baseline_branch_id: str
    challenger_branch_ids: list[str]
    latest_snapshot_id: None = None
    latest_ready: None = None
    blocked_reason: None = None
    missing_or_stale: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""


class CreateComparison:
    """Create a comparison intent between a baseline and one or more challenger branches."""

    def __init__(self, uow_factory: Any, governance_enabled: bool = True,
                 id_generator: IdGeneratorPort | None = None) -> None:
        self._uow_factory = uow_factory
        self._governance_enabled = governance_enabled
        self._id_generator = id_generator

    def __call__(self, command: CreateComparisonCommand) -> CreateComparisonResult:
        if not self._governance_enabled:
            raise GovernanceNotEnabled()

        spec = command.comparison_spec or dict(DEFAULT_COMPARISON_SPEC)

        with self._uow_factory.for_project(command.project_id) as uow:
            baseline = uow.branches.get_branch(command.baseline_branch_id)
            if baseline is None:
                raise CardreError(
                    f"BASELINE_BRANCH_NOT_FOUND: {command.baseline_branch_id}",
                    code="BASELINE_BRANCH_NOT_FOUND",
                    context={"branch_id": command.baseline_branch_id},
                    status_code=404,
                )

            for cid in command.challenger_branch_ids:
                if uow.branches.get_branch(cid) is None:
                    raise CardreError(
                        f"CHALLENGER_BRANCH_NOT_FOUND: {cid}",
                        code="CHALLENGER_BRANCH_NOT_FOUND",
                        context={"branch_id": cid},
                        status_code=404,
                    )

            plan = uow.plans.get_plan(command.plan_id)
            if plan is None:
                raise CardreError(
                    f"PLAN_NOT_FOUND: {command.plan_id}",
                    code="PLAN_NOT_FOUND",
                    context={"plan_id": command.plan_id},
                    status_code=404,
                )
            pid = plan.project_id if hasattr(plan, "project_id") else plan.get("project_id")
            if pid != command.project_id:
                raise CardreError(
                    f"PLAN_PROJECT_MISMATCH: {command.plan_id}",
                    code="PLAN_PROJECT_MISMATCH",
                    context={"plan_id": command.plan_id, "project_id": command.project_id},
                    status_code=409,
                )

            self._require_branch_for_plan(
                baseline, command.baseline_branch_id, command.project_id, command.plan_id,
                label="baseline",
            )
            for cid in command.challenger_branch_ids:
                challenger = uow.branches.get_branch(cid)
                if challenger is not None:
                    self._require_branch_for_plan(
                        challenger, cid, command.project_id, command.plan_id,
                        label="challenger",
                    )

            now = utc_now_iso()

            comparison_id = self._id_generator.new_id() if self._id_generator else str(uuid.uuid4())
            uow.comparisons.create_comparison_with_id(
                comparison_id,
                command.project_id,
                command.plan_id,
                command.baseline_branch_id,
                json.dumps(spec),
                created_reason=command.created_reason,
            )

            for idx, cid in enumerate(command.challenger_branch_ids):
                uow.comparisons.add_challenger_branch(comparison_id, cid, idx)

            uow.commit()

        return CreateComparisonResult(
            comparison_id=comparison_id,
            project_id=command.project_id,
            plan_id=command.plan_id,
            baseline_branch_id=command.baseline_branch_id,
            challenger_branch_ids=command.challenger_branch_ids,
            created_at=now,
        )

    @staticmethod
    def _require_branch_for_plan(
        branch: dict[str, Any],
        branch_id: str,
        project_id: str,
        plan_id: str,
        *,
        label: str,
    ) -> None:
        """Validate that a branch aggregate belongs to the given project and plan.

        A comparison must never aggregate branches from a different plan or
        project: that would forge cross-plan lineage, snapshots, and champion
        decisions. Both ownership and active status are enforced here so
        every comparison reference is a valid, live aggregate member.
        """
        if branch.get("project_id") != project_id or branch.get("plan_id") != plan_id:
            raise CardreError(
                f"BRANCH_SCOPE_MISMATCH: {branch_id}",
                code="BRANCH_SCOPE_MISMATCH",
                context={
                    "branch_id": branch_id,
                    "label": label,
                    "project_id": project_id,
                    "plan_id": plan_id,
                    "branch_project_id": branch.get("project_id"),
                    "branch_plan_id": branch.get("plan_id"),
                },
                status_code=409,
            )
        if branch.get("status") != "active":
            raise CardreError(
                f"BRANCH_NOT_ACTIVE: {branch_id}",
                code="BRANCH_NOT_ACTIVE",
                context={"branch_id": branch_id, "label": label, "status": branch.get("status")},
                status_code=409,
            )
