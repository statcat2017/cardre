"""Step repository — CRUD for plan_steps and plan_step_edges."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from cardre.domain.step import StepSpec

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class StepRepository:
    """Repository for plan steps and edges."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def get_steps(self, plan_version_id: str) -> list[StepSpec]:
        rows = self._store.execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (plan_version_id,),
        ).fetchall()
        return [self._row_to_step_spec(r) for r in rows]

    def insert_edge(
        self,
        plan_version_id: str,
        parent_step_id: str,
        child_step_id: str,
        edge_order: int = 0,
    ) -> None:
        self._store.execute(
            "INSERT OR IGNORE INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
            "VALUES (?, ?, ?, ?)",
            (plan_version_id, parent_step_id, child_step_id, edge_order),
        )

    def get_parent_edges(self, plan_version_id: str, child_step_id: str) -> list[dict[str, Any]]:
        rows = self._store.execute(
            "SELECT * FROM plan_step_edges WHERE plan_version_id = ? AND child_step_id = ? ORDER BY edge_order",
            (plan_version_id, child_step_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_child_edges(self, plan_version_id: str, parent_step_id: str) -> list[dict[str, Any]]:
        rows = self._store.execute(
            "SELECT * FROM plan_step_edges WHERE plan_version_id = ? AND parent_step_id = ? ORDER BY edge_order",
            (plan_version_id, parent_step_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_edges(self, plan_version_id: str) -> list[dict[str, Any]]:
        rows = self._store.execute(
            "SELECT * FROM plan_step_edges WHERE plan_version_id = ? ORDER BY edge_order",
            (plan_version_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_distinct_node_types(self, project_id: str) -> list[dict[str, Any]]:
        rows = self._store.execute(
            "SELECT DISTINCT ps.node_type, ps.node_version, ps.category "
            "FROM plan_steps ps "
            "JOIN plan_versions pv ON ps.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? "
            "ORDER BY ps.node_type",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_to_step_spec(row: dict[str, Any]) -> StepSpec:
        return StepSpec(
            step_id=row["step_id"],
            node_type=row["node_type"],
            node_version=row["node_version"],
            category=row["category"],
            params=json.loads(row["params_json"]),
            params_hash=row["params_hash"],
            parent_step_ids=[],  # derived via plan_step_edges at query time
            branch_label=row["branch_label"],
            position=row["position"],
            canonical_step_id=row["canonical_step_id"],
            branch_id=row["branch_id"],
        )
