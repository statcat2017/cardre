"""Branch repository — branch CRUD, step maps, comparisons, champion assignments."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

from cardre.audit import utc_now_iso

if TYPE_CHECKING:
    from cardre.store.project_store import ProjectStore


class BranchRepository:
    """CRUD for branches, branch step maps, comparisons, and champion assignments."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _db(self) -> sqlite3.Connection:
        return self._store._connect()

    def create(
        self,
        project_id: str,
        plan_id: str,
        name: str,
        branch_type: str,
        base_plan_version_id: str,
        head_plan_version_id: str,
        created_reason: str,
        branch_id: str | None = None,
        description: str | None = None,
        base_branch_id: str | None = None,
        branch_point_step_id: str | None = None,
        branch_point_canonical_step_id: str | None = None,
        segment_filter_spec_json: str | None = None,
    ) -> str:
        bid = branch_id or str(uuid.uuid4())
        now = utc_now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                "INSERT INTO plan_branches "
                "(branch_id, project_id, plan_id, name, description, branch_type, status, "
                " base_branch_id, base_plan_version_id, head_plan_version_id, "
                " branch_point_step_id, branch_point_canonical_step_id, "
                " segment_filter_spec_json, created_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bid, project_id, plan_id, name, description, branch_type,
                    base_branch_id, base_plan_version_id, head_plan_version_id,
                    branch_point_step_id, branch_point_canonical_step_id,
                    segment_filter_spec_json, created_reason, now, now,
                ),
            )
        return bid

    def get(self, branch_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM plan_branches WHERE branch_id = ?", (branch_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list(
        self,
        project_id: str,
        plan_id: str | None = None,
        branch_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM plan_branches WHERE project_id = ?"
        params: list[Any] = [project_id]
        if plan_id is not None:
            sql += " AND plan_id = ?"
            params.append(plan_id)
        if branch_type is not None:
            sql += " AND branch_type = ?"
            params.append(branch_type)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at"
        rows = self._db().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update_head(self, branch_id: str, head_plan_version_id: str) -> None:
        now = utc_now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                "UPDATE plan_branches SET head_plan_version_id = ?, updated_at = ? WHERE branch_id = ?",
                (head_plan_version_id, now, branch_id),
            )

    def create_step_map(
        self,
        branch_id: str,
        plan_version_id: str,
        canonical_step_id: str,
        step_id: str,
        is_shared_upstream: bool = False,
        is_branch_owned: bool = True,
        source_branch_id: str | None = None,
        source_step_id: str | None = None,
    ) -> str:
        map_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                "INSERT INTO branch_step_map "
                "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
                " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (map_id, branch_id, plan_version_id, canonical_step_id, step_id,
                 source_branch_id, source_step_id, int(is_shared_upstream), int(is_branch_owned), now),
            )
        return map_id

    def get_step_map(self, branch_id: str, plan_version_id: str) -> list[dict[str, Any]]:
        rows = self._db().execute(
            "SELECT * FROM branch_step_map WHERE branch_id = ? AND plan_version_id = ? "
            "ORDER BY created_at",
            (branch_id, plan_version_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_plan_version_ids(self, branch_id: str) -> list[str]:
        rows = self._db().execute(
            "SELECT DISTINCT plan_version_id FROM branch_step_map WHERE branch_id = ?",
            (branch_id,),
        ).fetchall()
        return [r["plan_version_id"] for r in rows]

    def get_output_artifact_ids(self, branch_id: str) -> list[list[str]]:
        rows = self._db().execute(
            "SELECT rs.output_artifact_ids_json FROM run_steps rs "
            "JOIN runs r ON rs.run_id = r.run_id "
            "WHERE r.branch_id = ? AND rs.status = 'succeeded' "
            "ORDER BY rs.started_at DESC",
            (branch_id,),
        ).fetchall()
        return [json.loads(r["output_artifact_ids_json"]) for r in rows if r["output_artifact_ids_json"]]

    def get_comparison(self, comparison_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM branch_comparisons WHERE comparison_id = ?",
            (comparison_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshots(self, comparison_id: str) -> list[dict[str, Any]]:
        rows = self._db().execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_id = ? "
            "ORDER BY created_at DESC",
            (comparison_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_champion_assignment(
        self, plan_id: str, champion_branch_id: str | None = None,
    ) -> dict[str, Any] | None:
        if champion_branch_id:
            row = self._db().execute(
                "SELECT * FROM champion_assignments "
                "WHERE plan_id = ? AND champion_branch_id = ? AND superseded_at IS NULL "
                "ORDER BY assigned_at DESC LIMIT 1",
                (plan_id, champion_branch_id),
            ).fetchone()
        else:
            row = self._db().execute(
                "SELECT * FROM champion_assignments "
                "WHERE plan_id = ? AND superseded_at IS NULL "
                "ORDER BY assigned_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment_by_branch(self, branch_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM champion_assignments "
            "WHERE champion_branch_id = ? AND superseded_at IS NULL "
            "ORDER BY assigned_at DESC LIMIT 1",
            (branch_id,),
        ).fetchone()
        return None if row is None else dict(row)
