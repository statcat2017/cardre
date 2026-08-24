"""AssignChampion — assign a branch as champion for a plan scope.

Ports ``champion_service.assign_champion`` into a single use case.
Validates branch, comparison, and snapshot readiness, then writes
the champion assignment and supersedes any previous champion for the
same scope — all in one UoW.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import CardreError, ErrorCode, GovernanceNotEnabled


@dataclass
class AssignChampionCommand:
    project_id: str
    plan_id: str
    branch_id: str
    comparison_id: str
    comparison_snapshot_id: str
    scope_type: str = "project"
    scope_key: str = "default"
    assigned_reason: str = ""


@dataclass
class AssignChampionResult:
    champion_assignment_id: str
    plan_id: str
    champion_branch_id: str
    previous_champion_branch_id: str | None = None
    scope_type: str = ""
    scope_key: str = ""
    assigned_at: str = ""
    assigned_reason: str = ""


class AssignChampion:
    """Assign a branch as champion, superseding any previous champion for the same scope."""

    def __init__(self, uow_factory: Any, governance_enabled: bool = True) -> None:
        self._uow_factory = uow_factory
        self._governance_enabled = governance_enabled

    def __call__(self, command: AssignChampionCommand) -> AssignChampionResult:
        if not self._governance_enabled:
            raise GovernanceNotEnabled()

        if not command.assigned_reason.strip():
            raise CardreError(
                "CHAMPION_REASON_REQUIRED: Champion assignment requires a non-empty rationale.",
                code=ErrorCode.CHAMPION_REASON_REQUIRED,
            )

        with self._uow_factory.for_project(command.project_id) as uow:
            branch = uow.branches.get_branch(command.branch_id)
            if branch is None:
                raise CardreError(
                    f"BRANCH_NOT_FOUND: champion branch ID {command.branch_id}",
                    code=ErrorCode.CHAMPION_BRANCH_NOT_FOUND,
                    context={"branch_id": command.branch_id},
                )
            if branch.get("status") != "active":
                raise CardreError(
                    f"BRANCH_NOT_ACTIVE: Branch {command.branch_id} is not active.",
                    code=ErrorCode.CHAMPION_BRANCH_INACTIVE,
                    context={"branch_id": command.branch_id},
                )
            if branch.get("project_id") != command.project_id or branch.get("plan_id") != command.plan_id:
                raise CardreError(
                    f"CHAMPION_BRANCH_MISMATCH: Branch {command.branch_id} does not belong to plan {command.plan_id}.",
                    code=ErrorCode.CHAMPION_BRANCH_MISMATCH,
                    context={"branch_id": command.branch_id, "plan_id": command.plan_id},
                )

            comparison = uow.comparisons.get_comparison(command.comparison_id)
            if comparison is None:
                raise CardreError(
                    f"COMPARISON_NOT_FOUND: {command.comparison_id}",
                    code=ErrorCode.COMPARISON_NOT_FOUND,
                    context={"comparison_id": command.comparison_id},
                )

            snap = uow.comparisons.get_comparison_snapshot(command.comparison_snapshot_id)
            if snap is None or snap["comparison_id"] != command.comparison_id:
                raise CardreError(
                    f"COMPARISON_SNAPSHOT_NOT_FOUND: {command.comparison_snapshot_id} "
                    f"does not belong to comparison {command.comparison_id}.",
                    code=ErrorCode.COMPARISON_SNAPSHOT_NOT_FOUND,
                    context={"comparison_snapshot_id": command.comparison_snapshot_id, "comparison_id": command.comparison_id},
                )

            readiness = json.loads(snap["readiness_json"])
            if not readiness.get("ready", False):
                raise CardreError(
                    "COMPARISON_NOT_READY: Comparison snapshot is not ready.",
                    code=ErrorCode.COMPARISON_NOT_READY,
                    context={"comparison_snapshot_id": command.comparison_snapshot_id},
                )

            source_versions = uow.comparisons.get_snapshot_plan_versions(command.comparison_snapshot_id)
            source_pv_ids = [r["plan_version_id"] for r in source_versions]
            if branch["head_plan_version_id"] not in source_pv_ids:
                raise CardreError(
                    f"STALE_SNAPSHOT: Branch {command.branch_id} head plan version "
                    f"{branch['head_plan_version_id']} is not in the snapshot source versions {source_pv_ids}. "
                    "Refresh the comparison before assigning champion.",
                    code=ErrorCode.STALE_SNAPSHOT,
                    context={"branch_id": command.branch_id, "comparison_id": command.comparison_id},
                )

            challenger_rows = uow.comparisons.get_challenger_branches(command.comparison_id)
            challenger_ids = [r["branch_id"] for r in challenger_rows]
            if command.branch_id not in challenger_ids and comparison["baseline_branch_id"] != command.branch_id:
                raise CardreError(
                    f"BRANCH_NOT_IN_COMPARISON: Branch {command.branch_id} is not included "
                    f"in comparison {command.comparison_id}.",
                    code=ErrorCode.BRANCH_NOT_IN_COMPARISON,
                    context={"branch_id": command.branch_id, "comparison_id": command.comparison_id},
                )

            # --- Transactional writes ---

            now = utc_now_iso()
            previous_id: str | None = None

            champ_id = uow.champion.insert_champion_assignment(
                command.project_id, command.plan_id,
                command.scope_type, command.scope_key,
                command.branch_id, command.comparison_id,
                command.comparison_snapshot_id, snap["comparison_artifact_id"],
                branch["head_plan_version_id"], command.assigned_reason,
            )

            previous_id = uow.champion.find_active_champion(
                command.project_id, command.plan_id,
                command.scope_type, command.scope_key,
                exclude_assignment_id=champ_id,
            )

            if previous_id is not None:
                uow.champion.supersede_champion(previous_id, champ_id)

            uow.commit()

        return AssignChampionResult(
            champion_assignment_id=champ_id,
            plan_id=command.plan_id,
            champion_branch_id=command.branch_id,
            previous_champion_branch_id=previous_id,
            scope_type=command.scope_type,
            scope_key=command.scope_key,
            assigned_at=now,
            assigned_reason=command.assigned_reason,
        )
