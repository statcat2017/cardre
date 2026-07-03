"""Champion assignment service — assign and query champion branches.

Port from v1 to v2 infrastructure.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.branch_repo import BranchRepository
from cardre.store.comparison_repo import ComparisonRepository
from cardre.store.db import ProjectStore


def assign_champion(
    store: ProjectStore,
    project_id: str,
    plan_id: str,
    branch_id: str,
    comparison_id: str,
    comparison_snapshot_id: str,
    scope_type: str = "project",
    scope_key: str = "default",
    assigned_reason: str = "",
) -> dict[str, Any]:
    """Assign a branch as champion.

    Requires:
      - Active branch with current successful evidence
      - A ready comparison snapshot that includes the selected branch
      - Non-empty rationale

    Supersedes any previous active champion for the same scope.
    """
    branches_repo = BranchRepository(store)
    comparison_repo = ComparisonRepository(store)

    if not assigned_reason.strip():
        raise ValueError("CHAMPION_REASON_REQUIRED: Champion assignment requires a non-empty rationale.")

    branch = branches_repo.get_branch(branch_id)
    if branch is None:
        raise ValueError(f"CHAMPION_BRANCH_NOT_FOUND: No branch with ID {branch_id}")
    if branch.get("status") != "active":
        raise ValueError(f"CHAMPION_BRANCH_INACTIVE: Branch {branch_id} is not active.")
    if branch["project_id"] != project_id or branch["plan_id"] != plan_id:
        raise ValueError(f"CHAMPION_BRANCH_MISMATCH: Branch {branch_id} does not belong to plan {plan_id}.")

    # Verify comparison exists
    comparison = comparison_repo.get_comparison(comparison_id)
    if comparison is None:
        raise ValueError(f"COMPARISON_NOT_FOUND: {comparison_id}")

    # Verify snapshot belongs to this comparison
    snap = branches_repo.get_comparison_snapshot(comparison_snapshot_id)
    if snap is None or snap["comparison_id"] != comparison_id:
        raise ValueError(f"COMPARISON_SNAPSHOT_NOT_FOUND: {comparison_snapshot_id} does not belong to comparison {comparison_id}.")

    readiness = json.loads(snap["readiness_json"])
    if not readiness.get("ready", False):
        raise ValueError("COMPARISON_NOT_READY: Comparison snapshot is not ready.")

    # Read source plan versions from relational table, not JSON array
    source_versions = comparison_repo.get_snapshot_plan_versions(comparison_snapshot_id)
    source_pv_ids = [r["plan_version_id"] for r in source_versions]
    if branch["head_plan_version_id"] not in source_pv_ids:
        raise ValueError(
            f"STALE_SNAPSHOT: Branch {branch_id} head plan version "
            f"{branch['head_plan_version_id']} is not in the snapshot source versions {source_pv_ids}. "
            "Refresh the comparison before assigning champion."
        )

    # Check if the branch is part of this comparison
    challenger_rows = comparison_repo.get_challenger_branches(comparison_id)
    challenger_ids = [r["branch_id"] for r in challenger_rows]
    if branch_id not in challenger_ids and comparison["baseline_branch_id"] != branch_id:
        raise ValueError(f"BRANCH_NOT_IN_COMPARISON: Branch {branch_id} is not included in comparison {comparison_id}.")

    # Supersede previous champion
    now = utc_now_iso()
    champ_id = str(uuid.uuid4())
    previous_id: str | None = None

    with store.transaction() as conn:
        # Insert new champion first so FK from previous can reference it
        conn.execute(
            "INSERT INTO champion_assignments "
            "(champion_assignment_id, project_id, plan_id, scope_type, scope_key, "
            " champion_branch_id, comparison_id, comparison_snapshot_id, comparison_artifact_id, "
            " selected_plan_version_id, assigned_reason, assigned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                champ_id, project_id, plan_id, scope_type, scope_key,
                branch_id, comparison_id, comparison_snapshot_id, snap["comparison_artifact_id"],
                branch["head_plan_version_id"], assigned_reason, now,
            ),
        )

        # Now supersede any previous active champion
        prev = conn.execute(
            "SELECT champion_assignment_id FROM champion_assignments "
            "WHERE project_id = ? AND plan_id = ? AND scope_type = ? AND scope_key = ? "
            "AND champion_assignment_id != ? AND superseded_at IS NULL "
            "ORDER BY assigned_at DESC LIMIT 1",
            (project_id, plan_id, scope_type, scope_key, champ_id),
        ).fetchone()

        if prev is not None:
            previous_id = prev["champion_assignment_id"]
            conn.execute(
                "UPDATE champion_assignments SET superseded_at = ?, superseded_by_assignment_id = ? "
                "WHERE champion_assignment_id = ?",
                (now, champ_id, previous_id),
            )

    return {
        "champion_assignment_id": champ_id,
        "plan_id": plan_id,
        "champion_branch_id": branch_id,
        "previous_champion_branch_id": previous_id,
        "scope_type": scope_type,
        "scope_key": scope_key,
        "assigned_at": now,
        "assigned_reason": assigned_reason,
    }


def supersede_champion_for_branch(
    store: ProjectStore,
    branch_id: str,
    new_plan_version_id: str,
) -> None:
    """Supersede any active champion assignment for a branch whose head
    has advanced to *new_plan_version_id*.

    When a branch head advances, its previous champion assignment (if any)
    is no longer valid because the evidence it was based on may have
    changed.  This function marks the old assignment as superseded so the
    branch must be re-evaluated before it can be champion again.
    """
    branches_repo = BranchRepository(store)
    assignment = branches_repo.get_champion_assignment_by_branch(branch_id)
    if assignment is None:
        return
    if assignment["selected_plan_version_id"] == new_plan_version_id:
        return
    now = utc_now_iso()
    with store.transaction() as txn:
        txn.execute(
            "UPDATE champion_assignments SET superseded_at = ? "
            "WHERE champion_assignment_id = ? AND superseded_at IS NULL",
            (now, assignment["champion_assignment_id"]),
        )


def get_champion(
    store: ProjectStore,
    plan_id: str,
    scope_type: str = "project",
    scope_key: str = "default",
) -> dict[str, Any] | None:
    """Get the active champion assignment for a plan and scope."""
    row = store.execute(
        "SELECT * FROM champion_assignments "
        "WHERE plan_id = ? AND scope_type = ? AND scope_key = ? "
        "AND superseded_at IS NULL ORDER BY assigned_at DESC LIMIT 1",
        (plan_id, scope_type, scope_key),
    ).fetchone()
    if row is None:
        return None
    return dict(row)
