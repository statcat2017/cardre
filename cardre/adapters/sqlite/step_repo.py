"""SQLite step repository — query object for plan_steps and plan_step_edges."""

from __future__ import annotations

import json
from typing import Any


class StepRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def get_steps(self, plan_version_id: str) -> list[Any]:
        from cardre.domain.step import StepSpec
        rows = self._conn.execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (plan_version_id,),
        ).fetchall()
        return [StepSpec(
            step_id=r["step_id"], node_type=r["node_type"],
            node_version=r["node_version"], category=r["category"],
            params=json.loads(r["params_json"]), params_hash=r["params_hash"],
            parent_step_ids=[], branch_label=r["branch_label"],
            position=r["position"], canonical_step_id=r["canonical_step_id"],
            branch_id=r["branch_id"],
        ) for r in rows]

    def insert_steps_and_edges(self, conn: Any, plan_version_id: str, steps: list[Any]) -> None:
        for step in steps:
            conn.execute(
                "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
                "params_json, params_hash, branch_label, position, canonical_step_id, branch_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (step.step_id, plan_version_id, step.node_type, step.node_version, step.category,
                 json.dumps(step.params), step.params_hash, step.branch_label,
                 step.position, step.canonical_step_id, step.branch_id),
            )
            for idx, pid in enumerate(step.parent_step_ids):
                conn.execute(
                    "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                    "VALUES (?, ?, ?, ?)", (plan_version_id, pid, step.step_id, idx),
                )

    def get_parent_edges(self, plan_version_id: str, child_step_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM plan_step_edges WHERE plan_version_id = ? AND child_step_id = ? ORDER BY edge_order",
            (plan_version_id, child_step_id),
        ).fetchall()]

    def get_child_edges(self, plan_version_id: str, parent_step_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM plan_step_edges WHERE plan_version_id = ? AND parent_step_id = ? ORDER BY edge_order",
            (plan_version_id, parent_step_id),
        ).fetchall()]

    def get_all_edges(self, plan_version_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM plan_step_edges WHERE plan_version_id = ? ORDER BY edge_order",
            (plan_version_id,),
        ).fetchall()]

    def get_distinct_node_types(self, project_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT DISTINCT ps.node_type, ps.node_version, ps.category "
            "FROM plan_steps ps JOIN plan_versions pv ON ps.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id WHERE p.project_id = ? ORDER BY ps.node_type",
            (project_id,),
        ).fetchall()]
