"""Run repository — CRUD for the runs table."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, TYPE_CHECKING

logger = logging.getLogger(__name__)

from cardre.domain.errors import ConcurrentRunError
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
        branch_id: str | None = None,
        force: bool = False,
    ) -> str:
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        columns = self._run_columns()
        insert_cols = ["run_id", "plan_version_id", "status", "started_at"]
        values: list[object] = [run_id, plan_version_id, "running", now]
        if "branch_id" in columns:
            insert_cols.append("branch_id")
            values.append(branch_id)
        if "force" in columns:
            insert_cols.append("force")
            values.append(1 if force else 0)
        if "heartbeat_at" in columns:
            insert_cols.append("heartbeat_at")
            values.append(now)

        with self._store.transaction("IMMEDIATE") as conn:
            if not force:
                sql = "SELECT 1 FROM runs WHERE plan_version_id = ? AND finished_at IS NULL"
                params: list[object] = [plan_version_id]
                if branch_id is None:
                    if "branch_id" in columns:
                        sql += " AND branch_id IS NULL"
                elif "branch_id" in columns:
                    sql += " AND branch_id = ?"
                    params.append(branch_id)
                existing = conn.execute(sql, tuple(params)).fetchone()
                if existing is not None:
                    raise ConcurrentRunError(
                        f"A run is already in progress for plan_version_id={plan_version_id!r}"
                    )
            conn.execute(
                f"INSERT INTO runs ({', '.join(insert_cols)}) VALUES ({', '.join(['?'] * len(insert_cols))})",
                tuple(values),
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

    def save_step(self, rs: Any) -> None:
        step_cols = self._step_columns()
        with self._store.transaction("IMMEDIATE") as conn:
            run_row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (rs.run_id,),
            ).fetchone()
            branch_id = run_row["branch_id"] if run_row is not None and "branch_id" in run_row.keys() else None
            if {"input_artifact_ids_json", "output_artifact_ids_json"}.issubset(step_cols):
                conn.execute(
                    "INSERT OR REPLACE INTO run_steps "
                    "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
                    " input_artifact_ids_json, output_artifact_ids_json, execution_fingerprint_json, "
                    " warnings_json, errors_json, is_carried_forward) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rs.run_step_id,
                        rs.run_id,
                        rs.step_id,
                        rs.plan_version_id,
                        rs.status.value if hasattr(rs.status, "value") else rs.status,
                        rs.started_at,
                        rs.finished_at,
                        json.dumps(getattr(rs, "input_artifact_ids", [])),
                        json.dumps(getattr(rs, "output_artifact_ids", [])),
                        json.dumps(rs.execution_fingerprint),
                        json.dumps(rs.warnings),
                        json.dumps(rs.errors),
                        0,
                    ),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO run_steps "
                    "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
                    " execution_fingerprint_json, warnings_json, errors_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rs.run_step_id,
                        rs.run_id,
                        rs.step_id,
                        rs.plan_version_id,
                        rs.status.value if hasattr(rs.status, "value") else rs.status,
                        rs.started_at,
                        rs.finished_at,
                        json.dumps(rs.execution_fingerprint),
                        json.dumps(rs.warnings),
                        json.dumps(rs.errors),
                    ),
                )
            for artifact_id in getattr(rs, "input_artifact_ids", []):
                conn.execute(
                    "INSERT OR IGNORE INTO artifact_lineage "
                    "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, artifact_id, direction, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        rs.run_id,
                        rs.run_step_id,
                        rs.plan_version_id,
                        rs.step_id,
                        branch_id,
                        artifact_id,
                        "input",
                        rs.started_at,
                    ),
                )
            for artifact_id in getattr(rs, "output_artifact_ids", []):
                conn.execute(
                    "INSERT OR IGNORE INTO artifact_lineage "
                    "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, artifact_id, direction, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        rs.run_id,
                        rs.run_step_id,
                        rs.plan_version_id,
                        rs.step_id,
                        branch_id,
                        artifact_id,
                        "output",
                        rs.started_at,
                    ),
                )

    def get_steps(self, run_id: str) -> list[JsonDict]:
        rows = self._store.execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at, run_step_id",
            (run_id,),
        ).fetchall()
        if hasattr(self._store, "_row_to_run_step"):
            return [self._store._row_to_run_step(r) for r in rows]  # type: ignore[attr-defined]
        return [dict(r) for r in rows]

    def get_step(self, run_step_id: str):
        row = self._store.execute(
            "SELECT * FROM run_steps WHERE run_step_id = ?",
            (run_step_id,),
        ).fetchone()
        if row is None:
            return None
        if hasattr(self._store, "_row_to_run_step"):
            return self._store._row_to_run_step(row)  # type: ignore[attr-defined]
        return dict(row)

    def get_artifact_ids_for_run(self, run_id: str) -> set[str]:
        if {"input_artifact_ids_json", "output_artifact_ids_json"}.issubset(self._step_columns()):
            rows = self._store.execute(
                "SELECT output_artifact_ids_json FROM run_steps WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            artifact_ids: set[str] = set()
            for row in rows:
                artifact_ids.update(json.loads(row["output_artifact_ids_json"]))
            return artifact_ids
        rows = self._store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_id = ? AND direction = 'output'",
            (run_id,),
        ).fetchall()
        return {r["artifact_id"] for r in rows}

    def get_artifact_ids_for_producing_step(self, step_id: str) -> set[str]:
        if {"output_artifact_ids_json"}.issubset(self._step_columns()):
            rows = self._store.execute(
                "SELECT output_artifact_ids_json FROM run_steps WHERE step_id = ?",
                (step_id,),
            ).fetchall()
            artifact_ids: set[str] = set()
            for row in rows:
                artifact_ids.update(json.loads(row["output_artifact_ids_json"]))
            return artifact_ids
        rows = self._store.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE step_id = ? AND direction = 'output'",
            (step_id,),
        ).fetchall()
        return {r["artifact_id"] for r in rows}

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
        return self._store._row_to_run_step(row) if hasattr(self._store, "_row_to_run_step") else dict(row)  # type: ignore[attr-defined]

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
        return self._store._row_to_run_step(row) if hasattr(self._store, "_row_to_run_step") else dict(row)  # type: ignore[attr-defined]

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

    def _step_columns(self) -> set[str]:
        rows = self._store.execute("PRAGMA table_info(run_steps)").fetchall()
        return {r["name"] for r in rows}

    def _table_exists(self, table: str) -> bool:
        row = self._store.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None
