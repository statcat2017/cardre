"""Run repository — run and run-step CRUD."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

from cardre.audit import ArtifactRef, RunStepRecord, utc_now_iso

if TYPE_CHECKING:
    from cardre.store.project_store import ProjectStore


class RunRepository:
    """CRUD for runs and run steps."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _db(self) -> sqlite3.Connection:
        return self._store._connect()

    def create(self, plan_version_id: str, branch_id: str | None = None) -> str:
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        if branch_id:
            self._db().execute(
                "INSERT INTO runs (run_id, plan_version_id, branch_id, status, started_at) "
                "VALUES (?, ?, ?, 'running', ?)",
                (run_id, plan_version_id, branch_id, now),
            )
        else:
            self._db().execute(
                "INSERT INTO runs (run_id, plan_version_id, status, started_at) "
                "VALUES (?, ?, 'running', ?)",
                (run_id, plan_version_id, now),
            )
        return run_id

    def finish(self, run_id: str, status: str = "succeeded") -> None:
        now = utc_now_iso()
        cursor = self._db().execute(
            "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ? AND status = 'running'",
            (status, now, run_id),
        )
        if cursor.rowcount == 0:
            import logging
            logging.getLogger(__name__).warning(
                "run_repo.finish: no running run found for %s (status=%s)", run_id, status,
            )

    def get(self, run_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_for_plan_version(self, plan_version_id: str | None = None) -> list[dict[str, Any]]:
        if plan_version_id is not None:
            rows = self._db().execute(
                "SELECT * FROM runs WHERE plan_version_id = ? ORDER BY started_at DESC",
                (plan_version_id,),
            ).fetchall()
        else:
            rows = self._db().execute(
                "SELECT * FROM runs ORDER BY started_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        rows = self._db().execute(
            "SELECT r.*, COALESCE(rs.step_count, 0) AS step_count FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "LEFT JOIN (SELECT run_id, COUNT(*) AS step_count FROM run_steps GROUP BY run_id) rs "
            "  ON r.run_id = rs.run_id "
            "WHERE p.project_id = ? "
            "ORDER BY r.started_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_step(self, rs: RunStepRecord) -> None:
        self._db().execute(
            "INSERT INTO run_steps "
            "(run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, input_artifact_ids_json, "
            " output_artifact_ids_json, execution_fingerprint_json, "
            " warnings_json, errors_json, is_carried_forward) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rs.run_step_id, rs.run_id, rs.step_id, rs.plan_version_id,
                rs.status, rs.started_at, rs.finished_at,
                json.dumps(rs.input_artifact_ids),
                json.dumps(rs.output_artifact_ids),
                json.dumps(rs.execution_fingerprint),
                json.dumps(rs.warnings),
                json.dumps(rs.errors),
                int(rs.is_carried_forward),
            ),
        )

    def get_steps(self, run_id: str) -> list[RunStepRecord]:
        rows = self._db().execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at, run_step_id",
            (run_id,),
        ).fetchall()
        return [self._store._row_to_run_step(r) for r in rows]

    def get_latest_successful_id(
        self, plan_version_id: str, branch_id: str | None = None,
    ) -> str | None:
        if branch_id:
            row = self._db().execute(
                "SELECT run_id FROM runs WHERE plan_version_id = ? AND branch_id = ? "
                "AND status = 'succeeded' ORDER BY started_at DESC LIMIT 1",
                (plan_version_id, branch_id),
            ).fetchone()
        else:
            row = self._db().execute(
                "SELECT run_id FROM runs WHERE plan_version_id = ? AND branch_id IS NULL "
                "AND status = 'succeeded' ORDER BY started_at DESC LIMIT 1",
                (plan_version_id,),
            ).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_id_for_plan(self, plan_id: str) -> str | None:
        row = self._db().execute(
            "SELECT r.run_id FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND r.status = 'succeeded' AND r.branch_id IS NULL "
            "ORDER BY r.started_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_any_successful_id_for_plan(self, plan_id: str) -> str | None:
        row = self._db().execute(
            "SELECT r.run_id FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND r.status = 'succeeded' "
            "ORDER BY r.started_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_step(
        self, plan_version_id: str, step_id: str, branch_id: str | None = None,
    ) -> RunStepRecord | None:
        if branch_id:
            row = self._db().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "WHERE rs.plan_version_id = ? AND rs.step_id = ? "
                "AND r.branch_id = ? AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_version_id, step_id, branch_id),
            ).fetchone()
        else:
            row = self._db().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "WHERE rs.plan_version_id = ? AND rs.step_id = ? "
                "AND r.branch_id IS NULL AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_version_id, step_id),
            ).fetchone()
        if row is None:
            return None
        return self._store._row_to_run_step(row)

    def get_latest_successful_step_across_plan(
        self, plan_id: str, step_id: str, branch_id: str | None = None,
    ) -> RunStepRecord | None:
        if branch_id:
            row = self._db().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
                "WHERE pv.plan_id = ? AND rs.step_id = ? "
                "AND r.branch_id = ? AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_id, step_id, branch_id),
            ).fetchone()
        else:
            row = self._db().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
                "WHERE pv.plan_id = ? AND rs.step_id = ? "
                "AND r.branch_id IS NULL AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_id, step_id),
            ).fetchone()
        if row is None:
            return None
        return self._store._row_to_run_step(row)
