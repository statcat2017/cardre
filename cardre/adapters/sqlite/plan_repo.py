"""SQLite plan repository — query object for plans and plan versions."""

from __future__ import annotations

import json
from typing import Any

from cardre.domain.plan import Plan, PlanVersion
from cardre.domain.step import StepSpec


class PlanRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def create_plan(self, project_id: str, name: str) -> str:
        import uuid

        from cardre.domain.diagnostics import utc_now_iso
        plan_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._conn.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, name, now),
        )
        return plan_id

    def get_plan(self, plan_id: str) -> Plan | None:
        row = self._conn.execute(
            "SELECT plan_id, project_id, name, created_at FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        return Plan(plan_id=row["plan_id"], project_id=row["project_id"], name=row["name"], created_at=row["created_at"])

    def list_for_project(self, project_id: str) -> list[Plan]:
        rows = self._conn.execute(
            "SELECT plan_id, project_id, name, created_at FROM plans WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [Plan(plan_id=r["plan_id"], project_id=r["project_id"], name=r["name"], created_at=r["created_at"]) for r in rows]

    def create_version(self, conn: Any, plan_id: str, steps: list[StepSpec] | None = None,
                       description: str = "", *, is_committed: bool = False) -> str:
        import uuid

        from cardre.domain.diagnostics import utc_now_iso
        plan_version_id = str(uuid.uuid4())
        now = utc_now_iso()
        max_ver = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM plan_versions WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (plan_version_id, plan_id, max_ver, 1 if is_committed else 0, now, description),
        )
        if steps:
            from cardre.adapters.sqlite.step_repo import StepRepo
            StepRepo(conn).insert_steps_and_edges(conn, plan_version_id, steps)
        return plan_version_id

    def get_version(self, plan_version_id: str) -> PlanVersion | None:
        row = self._conn.execute(
            "SELECT plan_version_id, plan_id, version_number, is_committed, created_at, description FROM plan_versions WHERE plan_version_id = ?",
            (plan_version_id,),
        ).fetchone()
        if row is None:
            return None
        return PlanVersion(
            plan_version_id=row["plan_version_id"], plan_id=row["plan_id"],
            version_number=row["version_number"], is_committed=bool(row["is_committed"]),
            created_at=row["created_at"], description=row["description"],
        )

    def get_version_steps(self, plan_version_id: str) -> list[StepSpec]:
        rows = self._conn.execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (plan_version_id,),
        ).fetchall()
        steps: list[StepSpec] = []
        for row in rows:
            parent_rows = self._conn.execute(
                "SELECT parent_step_id FROM plan_step_edges WHERE plan_version_id = ? AND child_step_id = ? ORDER BY edge_order",
                (plan_version_id, row["step_id"]),
            ).fetchall()
            steps.append(StepSpec(
                step_id=row["step_id"], node_type=row["node_type"],
                node_version=row["node_version"], category=row["category"],
                params=json.loads(row["params_json"]), params_hash=row["params_hash"],
                parent_step_ids=[r["parent_step_id"] for r in parent_rows],
                branch_label=row["branch_label"], position=row["position"],
                canonical_step_id=row["canonical_step_id"], branch_id=row["branch_id"],
            ))
        return steps

    def list_versions(self, plan_id: str) -> list[PlanVersion]:
        rows = self._conn.execute(
            "SELECT plan_version_id, plan_id, version_number, is_committed, created_at, description FROM plan_versions WHERE plan_id = ? ORDER BY version_number",
            (plan_id,),
        ).fetchall()
        return [PlanVersion(
            plan_version_id=r["plan_version_id"], plan_id=r["plan_id"],
            version_number=r["version_number"], is_committed=bool(r["is_committed"]),
            created_at=r["created_at"], description=r["description"],
        ) for r in rows]

    def get_latest_version_id(self, plan_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT plan_version_id FROM plan_versions WHERE plan_id = ? ORDER BY version_number DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["plan_version_id"]

    def get_plan_id_for_version(self, plan_version_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT plan_id FROM plan_versions WHERE plan_version_id = ?", (plan_version_id,)
        ).fetchone()
        return None if row is None else row["plan_id"]

    def update_version_description(self, plan_version_id: str, description: str) -> None:
        self._conn.execute(
            "UPDATE plan_versions SET description = ? WHERE plan_version_id = ?",
            (description, plan_version_id),
        )

    def commit_version(self, plan_version_id: str) -> None:
        self._conn.execute(
            "UPDATE plan_versions SET is_committed = 1 WHERE plan_version_id = ?",
            (plan_version_id,),
        )
