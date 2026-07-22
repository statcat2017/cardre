"""SQLite branch repository — query object for plan_branches and branch_step_map."""

from __future__ import annotations

import uuid
from typing import Any

from cardre.domain.diagnostics import utc_now_iso


class BranchRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def create_branch(self, project_id: str, plan_id: str, name: str, branch_type: str,
                      base_plan_version_id: str, head_plan_version_id: str, *,
                      description: str | None = None, base_branch_id: str | None = None,
                      branch_point_step_id: str | None = None,
                      branch_point_canonical_step_id: str | None = None,
                      segment_filter_spec_json: str | None = None,
                      created_reason: str = "") -> str:
        branch_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._conn.execute(
            "INSERT INTO plan_branches (branch_id, project_id, plan_id, name, description, "
            "branch_type, status, base_branch_id, base_plan_version_id, head_plan_version_id, "
            "branch_point_step_id, branch_point_canonical_step_id, segment_filter_spec_json, "
            "created_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (branch_id, project_id, plan_id, name, description, branch_type,
             base_branch_id, base_plan_version_id, head_plan_version_id,
             branch_point_step_id, branch_point_canonical_step_id, segment_filter_spec_json,
             created_reason, now, now),
        )
        return branch_id

    def get_branch(self, branch_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM plan_branches WHERE branch_id = ?", (branch_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_branches(self, project_id: str, plan_id: str | None = None,
             branch_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[str] = [project_id]
        if plan_id:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        if branch_type:
            clauses.append("branch_type = ?")
            params.append(branch_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        rows = self._conn.execute(
            f"SELECT * FROM plan_branches WHERE {' AND '.join(clauses)} ORDER BY created_at",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def update_head(self, branch_id: str, head_plan_version_id: str) -> None:
        self._conn.execute(
            "UPDATE plan_branches SET head_plan_version_id = ?, updated_at = ? WHERE branch_id = ?",
            (head_plan_version_id, utc_now_iso(), branch_id),
        )

    def create_step_map(self, branch_id: str, plan_version_id: str, canonical_step_id: str,
                        step_id: str, *, source_branch_id: str | None = None,
                        source_step_id: str | None = None,
                        is_shared_upstream: bool = False, is_branch_owned: bool = True) -> str:
        map_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO branch_step_map (branch_step_map_id, branch_id, plan_version_id, "
            "canonical_step_id, step_id, source_branch_id, source_step_id, "
            "is_shared_upstream, is_branch_owned, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (map_id, branch_id, plan_version_id, canonical_step_id, step_id,
             source_branch_id, source_step_id,
             int(is_shared_upstream), int(is_branch_owned), utc_now_iso()),
        )
        return map_id

    def get_step_map(self, branch_id: str, plan_version_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM branch_step_map WHERE branch_id = ? AND plan_version_id = ? ORDER BY created_at",
            (branch_id, plan_version_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_plan_version_ids(self, branch_id: str) -> list[str]:
        return [r["plan_version_id"] for r in self._conn.execute(
            "SELECT DISTINCT plan_version_id FROM branch_step_map WHERE branch_id = ?",
            (branch_id,),
        ).fetchall()]
