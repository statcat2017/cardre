"""Comparison repository — CRUD for branch_comparisons, comparison_challenger_branches,
branch_comparison_snapshots, and comparison_snapshot_plan_versions."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from cardre.domain.diagnostics import JsonDict, utc_now_iso

if TYPE_CHECKING:
    import sqlite3

    from cardre.store.db import ProjectStore


class ComparisonRepository:
    """Repository for comparison-related tables."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def create_comparison(
        self,
        project_id: str,
        plan_id: str,
        baseline_branch_id: str,
        comparison_spec: dict[str, Any] | None = None,
        created_reason: str | None = None,
    ) -> str:
        comparison_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._store.execute(
            "INSERT INTO branch_comparisons "
            "(comparison_id, project_id, plan_id, baseline_branch_id, comparison_spec_json, created_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                comparison_id, project_id, plan_id, baseline_branch_id,
                json.dumps(comparison_spec or {}), now, created_reason,
            ),
        )
        return comparison_id

    def get_comparison(self, comparison_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM branch_comparisons WHERE comparison_id = ?", (comparison_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_for_project(self, project_id: str, plan_id: str | None = None) -> list[JsonDict]:
        if plan_id:
            rows = self._store.execute(
                "SELECT * FROM branch_comparisons WHERE project_id = ? AND plan_id = ? ORDER BY created_at",
                (project_id, plan_id),
            ).fetchall()
        else:
            rows = self._store.execute(
                "SELECT * FROM branch_comparisons WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_challenger_branch(
        self,
        comparison_id: str,
        branch_id: str,
        position: int = 0,
    ) -> None:
        self._store.execute(
            "INSERT OR IGNORE INTO comparison_challenger_branches (comparison_id, branch_id, position) "
            "VALUES (?, ?, ?)",
            (comparison_id, branch_id, position),
        )

    def get_challenger_branches(self, comparison_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM comparison_challenger_branches WHERE comparison_id = ? ORDER BY position",
            (comparison_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_snapshot(
        self,
        comparison_id: str,
        project_id: str,
        plan_id: str,
        comparison_artifact_id: str,
        readiness: dict[str, Any] | None = None,
        created_reason: str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> str:
        snapshot_id = str(uuid.uuid4())
        now = utc_now_iso()
        sql = (
            "INSERT INTO branch_comparison_snapshots "
            "(comparison_snapshot_id, comparison_id, project_id, plan_id, "
            " comparison_artifact_id, readiness_json, created_at, created_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = (
            snapshot_id, comparison_id, project_id, plan_id,
            comparison_artifact_id, json.dumps(readiness or {}), now, created_reason,
        )
        if conn is not None:
            conn.execute(sql, params)
        else:
            self._store.execute(sql, params)
        return snapshot_id

    def add_snapshot_plan_version(
        self,
        comparison_snapshot_id: str,
        plan_version_id: str,
        branch_id: str | None = None,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        sql = (
            "INSERT OR IGNORE INTO comparison_snapshot_plan_versions "
            "(comparison_snapshot_id, plan_version_id, branch_id) "
            "VALUES (?, ?, ?)"
        )
        params = (comparison_snapshot_id, plan_version_id, branch_id)
        if conn is not None:
            conn.execute(sql, params)
        else:
            self._store.execute(sql, params)

    def get_snapshot_plan_versions(self, comparison_snapshot_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM comparison_snapshot_plan_versions WHERE comparison_snapshot_id = ?",
            (comparison_snapshot_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_comparison_snapshot(self, snapshot_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshots(self, comparison_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_id = ? ORDER BY created_at",
            (comparison_id,),
        ).fetchall()
        return [dict(r) for r in rows]
