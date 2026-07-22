"""SQLite champion repository — query object for champion_assignments."""

from __future__ import annotations

import uuid
from typing import Any

from cardre.domain.diagnostics import utc_now_iso


class ChampionRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def get_champion_assignment_for_project(self, project_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM champion_assignments WHERE project_id = ? AND superseded_at IS NULL ORDER BY assigned_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment(self, plan_id: str, champion_branch_id: str | None = None) -> dict[str, Any] | None:
        clauses = ["plan_id = ?", "superseded_at IS NULL"]
        params: list[str] = [plan_id]
        if champion_branch_id:
            clauses.append("champion_branch_id = ?")
            params.append(champion_branch_id)
        row = self._conn.execute(
            f"SELECT * FROM champion_assignments WHERE {' AND '.join(clauses)} ORDER BY assigned_at DESC LIMIT 1",
            params,
        ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment_by_branch(self, branch_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM champion_assignments WHERE champion_branch_id = ? AND superseded_at IS NULL ORDER BY assigned_at DESC LIMIT 1",
            (branch_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def insert_champion_assignment(self, conn: Any, project_id: str, plan_id: str, scope_type: str, scope_key: str,
                                   champion_branch_id: str, comparison_id: str, comparison_snapshot_id: str,
                                   comparison_artifact_id: str, selected_plan_version_id: str,
                                   assigned_reason: str, assigned_by: str | None = None) -> str:
        assignment_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO champion_assignments (champion_assignment_id, project_id, plan_id, scope_type, scope_key, "
            "champion_branch_id, comparison_id, comparison_snapshot_id, comparison_artifact_id, "
            "selected_plan_version_id, assigned_reason, assigned_by, assigned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (assignment_id, project_id, plan_id, scope_type, scope_key, champion_branch_id,
             comparison_id, comparison_snapshot_id, comparison_artifact_id,
             selected_plan_version_id, assigned_reason, assigned_by, utc_now_iso()),
        )
        return assignment_id

    def supersede_champion(self, conn: Any, assignment_id: str, superseded_by: str) -> None:
        conn.execute(
            "UPDATE champion_assignments SET superseded_at = ?, superseded_by_assignment_id = ? "
            "WHERE champion_assignment_id = ?",
            (utc_now_iso(), superseded_by, assignment_id),
        )
