"""Run repository — CRUD for the runs table."""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from cardre.domain.diagnostics import JsonDict, utc_now_iso

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class RunRepository:
    """Repository for runs."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def append_diagnostic(self, run_id: str, diagnostic: dict) -> None:
        # Must match diagnostics table in REVIEW_TABLES_SQL (schema.py).
        # Extra fields (plan_version_id, category, etc.) go into context_json.
        self._store.execute(
            "CREATE TABLE IF NOT EXISTS diagnostics ("
            "diagnostic_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, "
            "code TEXT NOT NULL, message TEXT NOT NULL, source TEXT, "
            "severity TEXT NOT NULL DEFAULT 'error', "
            "context_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"
        )
        extra = {k: v for k, v in diagnostic.items()
                 if k not in {"code", "message", "source", "severity"}}
        self._store.execute(
            "INSERT INTO diagnostics (diagnostic_id, run_id, code, message, source, severity, context_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                run_id,
                diagnostic.get("code", "UNKNOWN"),
                diagnostic.get("message", ""),
                diagnostic.get("source"),
                diagnostic.get("severity", "error"),
                json.dumps(extra),
                diagnostic.get("created_at", utc_now_iso()),
            ),
        )

    def get_diagnostics(self, run_id: str) -> list[dict]:
        if not self._table_exists("diagnostics"):
            return []
        rows = self._store.execute(
            "SELECT * FROM diagnostics WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        out: list[dict] = []
        for row in rows:
            data = dict(row)
            context = json.loads(data.pop("context_json", "{}")) if data.get("context_json") else {}
            data.update(context)
            out.append(data)
        return out

    def create(
        self,
        plan_version_id: str,
        run_scope: str = "full_plan",
        branch_id: str | None = None,
        target_step_id: str | None = None,
        force: bool = False,
        requested_by: str | None = None,
        request_id: str | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._store.execute(
            """INSERT INTO runs
               (run_id, plan_version_id, status, run_scope, branch_id,
                target_step_id, force, requested_by, request_id,
                created_at, started_at, heartbeat_at)
               VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, plan_version_id, run_scope, branch_id, target_step_id,
             int(force), requested_by, request_id, now, now, now),
        )
        return run_id

    def heartbeat(self, run_id: str) -> None:
        if self._run_columns().intersection({"heartbeat_at"}):
            cursor = self._store.execute(
                "UPDATE runs SET heartbeat_at = ? WHERE run_id = ? AND status = 'running'",
                (utc_now_iso(), run_id),
            )
            if cursor.rowcount == 0:
                logger.warning("heartbeat: no running run found for run_id=%s", run_id)

    def set_active_step(self, run_id: str, step_id: str | None) -> None:
        row = self._store.execute("SELECT metadata_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return
        metadata = json.loads(row["metadata_json"] or "{}")
        if step_id is None:
            metadata.pop("active_step_id", None)
        else:
            metadata["active_step_id"] = step_id
        self._store.execute(
            "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
            (json.dumps(metadata), run_id),
        )

    def get_active_step(self, run_id: str) -> str | None:
        row = self._store.execute("SELECT metadata_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"] or "{}")
        return metadata.get("active_step_id")

    def get(self, run_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        return d

    def finish(self, run_id: str, status: str = "succeeded") -> None:
        now = utc_now_iso()
        cursor = self._store.execute(
            "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ? AND status = 'running'",
            (status, now, run_id),
        )
        if cursor.rowcount == 0:
            logger.warning("finish: no running run found for run_id=%s", run_id)

    def update_status(self, run_id: str, status: str) -> None:
        self._store.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?",
            (status, run_id),
        )

    def get_steps(self, run_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at, run_step_id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_step(self, run_step_id: str):
        row = self._store.execute(
            "SELECT * FROM run_steps WHERE run_step_id = ?",
            (run_step_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_latest_successful_id(self, plan_version_id: str, branch_id: str | None = None) -> str | None:
        sql = "SELECT run_id FROM runs WHERE plan_version_id = ? AND status = 'succeeded'"
        params: list[object] = [plan_version_id]
        if "branch_id" in self._run_columns():
            if branch_id is None:
                sql += " AND branch_id IS NULL"
            else:
                sql += " AND branch_id = ?"
                params.append(branch_id)
        sql += " ORDER BY started_at DESC LIMIT 1"
        row = self._store.execute(sql, tuple(params)).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_id_for_plan(self, plan_id: str) -> str | None:
        sql = (
            "SELECT r.run_id FROM runs r JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND r.status = 'succeeded'"
        )
        params: list[object] = [plan_id]
        if "branch_id" in self._run_columns():
            sql += " AND r.branch_id IS NULL"
        sql += " ORDER BY r.started_at DESC LIMIT 1"
        row = self._store.execute(sql, tuple(params)).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_step(self, plan_version_id: str, step_id: str, branch_id: str | None = None):
        sql = (
            "SELECT rs.* FROM run_steps rs JOIN runs r ON rs.run_id = r.run_id "
            "WHERE rs.plan_version_id = ? AND rs.step_id = ? AND rs.status = 'succeeded'"
        )
        params: list[object] = [plan_version_id, step_id]
        if "branch_id" in self._run_columns():
            if branch_id is None:
                sql += " AND r.branch_id IS NULL"
            else:
                sql += " AND r.branch_id = ?"
                params.append(branch_id)
        sql += " ORDER BY rs.started_at DESC LIMIT 1"
        row = self._store.execute(sql, tuple(params)).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_latest_successful_step_across_plan(self, plan_id: str, step_id: str, branch_id: str | None = None):
        sql = (
            "SELECT rs.* FROM run_steps rs JOIN runs r ON rs.run_id = r.run_id "
            "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND rs.step_id = ? AND rs.status = 'succeeded'"
        )
        params: list[object] = [plan_id, step_id]
        if "branch_id" in self._run_columns():
            if branch_id is None:
                sql += " AND r.branch_id IS NULL"
            else:
                sql += " AND r.branch_id = ?"
                params.append(branch_id)
        sql += " ORDER BY rs.started_at DESC LIMIT 1"
        row = self._store.execute(sql, tuple(params)).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_any_successful_id_for_plan(self, plan_id: str) -> str | None:
        return self.get_latest_successful_id_for_plan(plan_id)

    def list_for_plan_version(self, plan_version_id: str | None = None) -> list[JsonDict]:
        if plan_version_id is None:
            rows = self._store.execute(
                "SELECT * FROM runs ORDER BY started_at DESC"
            ).fetchall()
        else:
            rows = self._store.execute(
                "SELECT * FROM runs WHERE plan_version_id = ? ORDER BY started_at DESC",
                (plan_version_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_for_project(self, project_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT r.* FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? ORDER BY r.started_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _run_columns(self) -> set[str]:
        rows = self._store.execute("PRAGMA table_info(runs)").fetchall()
        return {r["name"] for r in rows}

    def _table_exists(self, table: str) -> bool:
        row = self._store.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None
