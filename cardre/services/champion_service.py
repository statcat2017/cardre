"""Champion assignment service — assign and query champion branches."""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.audit import utc_now_iso
from cardre.store import ProjectStore


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
    if not assigned_reason.strip():
        raise ValueError("CHAMPION_REASON_REQUIRED: Champion assignment requires a non-empty rationale.")

    branch = store.get_branch(branch_id)
    if branch is None:
        raise ValueError(f"CHAMPION_BRANCH_NOT_FOUND: No branch with ID {branch_id}")
    if branch.get("status") != "active":
        raise ValueError(f"CHAMPION_BRANCH_INACTIVE: Branch {branch_id} is not active.")
    if branch["project_id"] != project_id or branch["plan_id"] != plan_id:
        raise ValueError(f"CHAMPION_BRANCH_MISMATCH: Branch {branch_id} does not belong to plan {plan_id}.")

    # Verify comparison snapshot exists and is ready
    snap = store._connect().execute(
        "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
        (comparison_snapshot_id,),
    ).fetchone()
    if snap is None:
        raise ValueError(f"COMPARISON_SNAPSHOT_NOT_FOUND: {comparison_snapshot_id}")

    readiness = json.loads(snap["readiness_json"])
    if not readiness.get("ready", False):
        raise ValueError("COMPARISON_NOT_READY: Comparison snapshot is not ready.")

    comparison = store._connect().execute(
        "SELECT * FROM branch_comparisons WHERE comparison_id = ?",
        (comparison_id,),
    ).fetchone()
    if comparison is None:
        raise ValueError(f"COMPARISON_NOT_FOUND: {comparison_id}")

    champ_ids = json.loads(comparison["challenger_branch_ids_json"])
    if branch_id not in champ_ids and comparison["baseline_branch_id"] != branch_id:
        raise ValueError(f"BRANCH_NOT_IN_COMPARISON: Branch {branch_id} is not included in comparison {comparison_id}.")

    # Supersede previous champion
    now = utc_now_iso()
    champ_id = str(uuid.uuid4())
    previous_id: str | None = None

    with store.transaction() as conn:
        prev = conn.execute(
            "SELECT champion_assignment_id FROM champion_assignments "
            "WHERE project_id = ? AND plan_id = ? AND scope_type = ? AND scope_key = ? "
            "AND superseded_at IS NULL ORDER BY assigned_at DESC LIMIT 1",
            (project_id, plan_id, scope_type, scope_key),
        ).fetchone()

        if prev is not None:
            previous_id = prev["champion_assignment_id"]
            conn.execute(
                "UPDATE champion_assignments SET superseded_at = ?, superseded_by_assignment_id = ? "
                "WHERE champion_assignment_id = ?",
                (now, champ_id, previous_id),
            )

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


def get_champion(
    store: ProjectStore,
    plan_id: str,
    scope_type: str = "project",
    scope_key: str = "default",
) -> dict[str, Any] | None:
    """Get the active champion assignment for a plan and scope."""
    row = store._connect().execute(
        "SELECT * FROM champion_assignments "
        "WHERE plan_id = ? AND scope_type = ? AND scope_key = ? "
        "AND superseded_at IS NULL ORDER BY assigned_at DESC LIMIT 1",
        (plan_id, scope_type, scope_key),
    ).fetchone()
    if row is None:
        return None
    return dict(row)
