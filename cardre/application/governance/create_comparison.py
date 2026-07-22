"""CreateComparison — create a comparison intent between baseline and challenger branches.

Ports ``comparison_service.create_comparison`` into a single use case
that owns its own UoW.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

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

    def __init__(self, uow_factory: Any, governance_enabled: bool = True) -> None:
        self._uow_factory = uow_factory
        self._governance_enabled = governance_enabled

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

            now = utc_now_iso()

            comparison_id = str(uuid.uuid4())
            conn = uow._conn
            conn.execute(
                "INSERT INTO branch_comparisons "
                "(comparison_id, project_id, plan_id, baseline_branch_id, "
                " comparison_spec_json, created_at, created_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    comparison_id,
                    command.project_id,
                    command.plan_id,
                    command.baseline_branch_id,
                    json.dumps(spec),
                    now,
                    command.created_reason,
                ),
            )

            for idx, cid in enumerate(command.challenger_branch_ids):
                conn.execute(
                    "INSERT OR IGNORE INTO comparison_challenger_branches "
                    "(comparison_id, branch_id, position) VALUES (?, ?, ?)",
                    (comparison_id, cid, idx),
                )

            uow.commit()

        return CreateComparisonResult(
            comparison_id=comparison_id,
            project_id=command.project_id,
            plan_id=command.plan_id,
            baseline_branch_id=command.baseline_branch_id,
            challenger_branch_ids=command.challenger_branch_ids,
            created_at=now,
        )
