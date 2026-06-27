"""Plan repository — plan and plan-version CRUD."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

from cardre.audit import StepSpec, utc_now_iso

if TYPE_CHECKING:
    from cardre.store.project_store import ProjectStore


class PlanRepository:
    """CRUD for plans and plan versions."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _db(self) -> sqlite3.Connection:
        return self._store._connect()

    def create(self, project_id: str, name: str) -> str:
        plan_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._db().execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, name, now),
        )
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        rows = self._db().execute(
            "SELECT * FROM plans WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_version(
        self,
        plan_id: str,
        steps: list[StepSpec],
        description: str = "",
    ) -> str:
        with self._store.transaction() as conn:
            return self._store._insert_plan_version_and_steps(conn, plan_id, steps, description)

    def get_version(self, plan_version_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM plan_versions WHERE plan_version_id = ?", (plan_version_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def get_version_steps(self, plan_version_id: str) -> list[StepSpec]:
        rows = self._db().execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (plan_version_id,),
        ).fetchall()
        if not rows:
            return []
        col_names = rows[0].keys()
        has_canonical = "canonical_step_id" in col_names
        has_branch = "branch_id" in col_names
        return [
            self._store._migrate_step_spec(StepSpec(
                step_id=r["step_id"],
                node_type=r["node_type"],
                node_version=r["node_version"],
                category=r["category"],
                params=json.loads(r["params_json"]),
                params_hash=r["params_hash"],
                parent_step_ids=json.loads(r["parent_step_ids_json"]),
                branch_label=r["branch_label"],
                position=r["position"],
                canonical_step_id=r["canonical_step_id"] if has_canonical else r["step_id"],
                branch_id=r["branch_id"] if has_branch else None,
            ))
            for r in rows
        ]

    def get_latest_version_id(self, plan_id: str) -> str | None:
        row = self._db().execute(
            "SELECT plan_version_id FROM plan_versions WHERE plan_id = ? "
            "ORDER BY version_number DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["plan_version_id"]

    def list_versions(self, plan_id: str) -> list[dict[str, Any]]:
        rows = self._db().execute(
            "SELECT * FROM plan_versions WHERE plan_id = ? ORDER BY version_number",
            (plan_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_plan_id_for_version(self, plan_version_id: str) -> str | None:
        row = self._db().execute(
            "SELECT plan_id FROM plan_versions WHERE plan_version_id = ?",
            (plan_version_id,),
        ).fetchone()
        return None if row is None else row["plan_id"]
