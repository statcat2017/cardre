"""Plan repository — CRUD for plans and plan versions."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from cardre.domain.diagnostics import JsonDict, utc_now_iso
from cardre.domain.step import StepSpec

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class PlanRepository:
    """Repository for plans and plan versions."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def create_plan(self, project_id: str, name: str) -> str:
        plan_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, name, now),
        )
        return plan_id

    def get_plan(self, plan_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_for_project(self, project_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM plans WHERE project_id = ? ORDER BY created_at", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def create_version(
        self,
        plan_id: str,
        steps: list[StepSpec] | None = None,
        description: str = "",
        *,
        is_committed: bool = False,
    ) -> str:
        plan_version_id = str(uuid.uuid4())
        now = utc_now_iso()
        max_ver = self._store.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM plan_versions WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()[0]
        self._store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (plan_version_id, plan_id, max_ver, 1 if is_committed else 0, now, description),
        )
        if steps:
            for step in steps:
                self._store.execute(
                    "INSERT INTO plan_steps "
                    "(step_id, plan_version_id, node_type, node_version, category, "
                    " params_json, params_hash, branch_label, position, canonical_step_id, branch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        step.step_id,
                        plan_version_id,
                        step.node_type,
                        step.node_version,
                        step.category,
                        json.dumps(step.params),
                        step.params_hash,
                        step.branch_label,
                        step.position,
                        step.canonical_step_id,
                        step.branch_id,
                    ),
                )
                for index, parent_step_id in enumerate(step.parent_step_ids):
                    self._store.execute(
                        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
                        "VALUES (?, ?, ?, ?)",
                        (plan_version_id, parent_step_id, step.step_id, index),
                    )
        return plan_version_id

    def get_version(self, plan_version_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM plan_versions WHERE plan_version_id = ?", (plan_version_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def get_version_steps(self, plan_version_id: str) -> list[StepSpec]:
        rows = self._store.execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (plan_version_id,),
        ).fetchall()
        steps: list[StepSpec] = []
        for row in rows:
            parent_rows = self._store.execute(
                "SELECT parent_step_id FROM plan_step_edges WHERE plan_version_id = ? AND child_step_id = ? ORDER BY edge_order",
                (plan_version_id, row["step_id"]),
            ).fetchall()
            parent_step_ids = [r["parent_step_id"] for r in parent_rows]
            steps.append(
                StepSpec(
                    step_id=row["step_id"],
                    node_type=row["node_type"],
                    node_version=row["node_version"],
                    category=row["category"],
                    params=json.loads(row["params_json"]),
                    params_hash=row["params_hash"],
                    parent_step_ids=parent_step_ids,
                    branch_label=row["branch_label"],
                    position=row["position"],
                    canonical_step_id=row["canonical_step_id"],
                    branch_id=row["branch_id"],
                )
            )
        return steps

    def list_versions(self, plan_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM plan_versions WHERE plan_id = ? ORDER BY version_number", (plan_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_version_id(self, plan_id: str) -> str | None:
        row = self._store.execute(
            "SELECT plan_version_id FROM plan_versions WHERE plan_id = ? ORDER BY version_number DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["plan_version_id"]

    def get_plan_id_for_version(self, plan_version_id: str) -> str | None:
        row = self._store.execute(
            "SELECT plan_id FROM plan_versions WHERE plan_version_id = ?",
            (plan_version_id,),
        ).fetchone()
        return None if row is None else row["plan_id"]

    def update_version_description(self, plan_version_id: str, description: str) -> None:
        self._store.execute(
            "UPDATE plan_versions SET description = ? WHERE plan_version_id = ?",
            (description, plan_version_id),
        )

    def commit_version(self, plan_version_id: str) -> None:
        self._store.execute(
            "UPDATE plan_versions SET is_committed = 1 WHERE plan_version_id = ?",
            (plan_version_id,),
        )
