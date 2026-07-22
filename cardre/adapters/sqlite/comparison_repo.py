"""SQLite comparison repository — query object for branch comparisons."""

from __future__ import annotations

import uuid
from typing import Any

from cardre.domain.diagnostics import utc_now_iso


class ComparisonRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def create_comparison(self, project_id: str, plan_id: str, baseline_branch_id: str,
                          comparison_spec_json: str, *,
                          created_reason: str | None = None) -> str:
        comparison_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO branch_comparisons (comparison_id, project_id, plan_id, baseline_branch_id, "
            "comparison_spec_json, created_at, created_reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (comparison_id, project_id, plan_id, baseline_branch_id,
             comparison_spec_json, utc_now_iso(), created_reason),
        )
        return comparison_id

    def get_comparison(self, comparison_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM branch_comparisons WHERE comparison_id = ?", (comparison_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_for_project(self, project_id: str, plan_id: str | None = None) -> list[dict]:
        if plan_id:
            rows = self._conn.execute(
                "SELECT * FROM branch_comparisons WHERE project_id = ? AND plan_id = ? ORDER BY created_at",
                (project_id, plan_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM branch_comparisons WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_challenger_branch(self, comparison_id: str, branch_id: str, position: int = 0) -> None:
        self._conn.execute(
            "INSERT INTO comparison_challenger_branches (comparison_id, branch_id, position) VALUES (?, ?, ?)",
            (comparison_id, branch_id, position),
        )

    def get_challenger_branches(self, comparison_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM comparison_challenger_branches WHERE comparison_id = ? ORDER BY position",
            (comparison_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_snapshot(self, conn: Any, comparison_id: str, project_id: str, plan_id: str,
                        comparison_artifact_id: str, readiness_json: str, *,
                        created_reason: str | None = None) -> str:
        snapshot_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO branch_comparison_snapshots (comparison_snapshot_id, comparison_id, project_id, "
            "plan_id, comparison_artifact_id, readiness_json, created_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (snapshot_id, comparison_id, project_id, plan_id, comparison_artifact_id,
             readiness_json, utc_now_iso(), created_reason),
        )
        return snapshot_id

    def add_snapshot_plan_version(self, conn: Any, comparison_snapshot_id: str,
                                  plan_version_id: str, branch_id: str | None = None) -> None:
        conn.execute(
            "INSERT INTO comparison_snapshot_plan_versions (comparison_snapshot_id, plan_version_id, branch_id) "
            "VALUES (?, ?, ?)",
            (comparison_snapshot_id, plan_version_id, branch_id),
        )

    def get_snapshot_plan_versions(self, comparison_snapshot_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM comparison_snapshot_plan_versions WHERE comparison_snapshot_id = ?",
            (comparison_snapshot_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_comparison_snapshot(self, snapshot_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshots(self, comparison_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_id = ? ORDER BY created_at",
            (comparison_id,),
        ).fetchall()
        return [dict(r) for r in rows]
