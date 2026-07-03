"""Branch repository — CRUD for branch, comparison, champion tables."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, List

from cardre.domain.diagnostics import JsonDict, utc_now_iso

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class BranchRepository:
    """Repository for branch-related tables."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

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
        return self.create_branch(
            project_id,
            plan_id,
            name,
            branch_type,
            base_plan_version_id,
            head_plan_version_id,
            created_reason,
            branch_id=branch_id,
            description=description,
            base_branch_id=base_branch_id,
            branch_point_step_id=branch_point_step_id,
            branch_point_canonical_step_id=branch_point_canonical_step_id,
            segment_filter_spec_json=segment_filter_spec_json,
        )

    # ------------------------------------------------------------------
    # Plan branches
    # ------------------------------------------------------------------

    def create_branch(
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
        self._store.execute(
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

    def get_branch(self, branch_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM plan_branches WHERE branch_id = ?", (branch_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def get(self, branch_id: str) -> JsonDict | None:
        return self.get_branch(branch_id)

    def list(
        self,
        project_id: str,
        plan_id: str | None = None,
        branch_type: str | None = None,
        status: str | None = None,
    ) -> list[JsonDict]:
        sql = ["SELECT * FROM plan_branches WHERE project_id = ?"]
        params: list[object] = [project_id]
        if plan_id is not None:
            sql.append("AND plan_id = ?")
            params.append(plan_id)
        if branch_type is not None:
            sql.append("AND branch_type = ?")
            params.append(branch_type)
        if status is not None:
            sql.append("AND status = ?")
            params.append(status)
        sql.append("ORDER BY created_at")
        rows = self._store.execute(" ".join(sql), tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def update_head(self, branch_id: str, head_plan_version_id: str) -> None:
        self._store.execute(
            "UPDATE plan_branches SET head_plan_version_id = ?, updated_at = ? WHERE branch_id = ?",
            (head_plan_version_id, utc_now_iso(), branch_id),
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
        row_id = str(uuid.uuid4())
        self._store.execute(
            "INSERT INTO branch_step_map "
            "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
            " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                branch_id,
                plan_version_id,
                canonical_step_id,
                step_id,
                source_branch_id,
                source_step_id,
                1 if is_shared_upstream else 0,
                1 if is_branch_owned else 0,
                utc_now_iso(),
            ),
        )
        return row_id

    def get_step_map(self, branch_id: str, plan_version_id: str) -> List[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM branch_step_map WHERE branch_id = ? AND plan_version_id = ? ORDER BY created_at",
            (branch_id, plan_version_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_plan_version_ids(self, branch_id: str) -> List[str]:
        rows = self._store.execute(
            "SELECT DISTINCT plan_version_id FROM branch_step_map WHERE branch_id = ? ORDER BY plan_version_id",
            (branch_id,),
        ).fetchall()
        return [r["plan_version_id"] for r in rows]

    def get_output_artifact_ids(self, branch_id: str) -> List[List[str]]:
        rows = self._store.execute(
            "SELECT rs.run_step_id, al.artifact_id "
            "FROM artifact_lineage al "
            "JOIN run_steps rs ON rs.run_step_id = al.run_step_id "
            "WHERE al.branch_id = ? AND al.direction = 'output' "
            "ORDER BY rs.started_at, al.created_at",
            (branch_id,),
        ).fetchall()
        grouped: list[list[str]] = []
        current_step: str | None = None
        current_ids: list[str] = []
        for row in rows:
            step_id = row["run_step_id"]
            if current_step is None or step_id != current_step:
                if current_ids:
                    grouped.append(current_ids)
                current_step = step_id
                current_ids = []
            current_ids.append(row["artifact_id"])
        if current_ids:
            grouped.append(current_ids)
        return grouped

    # ------------------------------------------------------------------
    # Champion assignments
    # ------------------------------------------------------------------

    def get_champion_assignment(self, plan_id: str, champion_branch_id: str | None = None) -> JsonDict | None:
        if champion_branch_id:
            row = self._store.execute(
                "SELECT * FROM champion_assignments WHERE plan_id = ? AND champion_branch_id = ? AND superseded_at IS NULL",
                (plan_id, champion_branch_id),
            ).fetchone()
        else:
            row = self._store.execute(
                "SELECT * FROM champion_assignments WHERE plan_id = ? AND superseded_at IS NULL",
                (plan_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def get_champion_assignment_by_branch(self, branch_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM champion_assignments WHERE champion_branch_id = ? AND superseded_at IS NULL",
            (branch_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison(self, comparison_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM branch_comparisons WHERE comparison_id = ?",
            (comparison_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshot(self, snapshot_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshots(self, comparison_id: str) -> List[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_id = ? ORDER BY created_at",
            (comparison_id,),
        ).fetchall()
        return [dict(r) for r in rows]
