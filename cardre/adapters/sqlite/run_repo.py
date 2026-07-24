"""SQLite run repository — query object for runs."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from cardre.domain.run import Run, RunStatus, RunStep, RunStepStatus

logger = logging.getLogger(__name__)


class RunRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _branch_filter(self, branch_id: str | None) -> tuple[str, list[str]]:
        if branch_id is not None:
            return "AND branch_id = ?", [branch_id]
        return "AND branch_id IS NULL", []

    def create(self, plan_version_id: str, run_scope: str = "full_plan",
               branch_id: str | None = None, force: bool = False,
               requested_by: str | None = None, request_id: str | None = None) -> str:
        from cardre.domain.run import RunScope
        RunScope(run_scope)
        from cardre.domain.diagnostics import utc_now_iso
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, branch_id, "
            "force, requested_by, request_id, created_at, started_at, heartbeat_at) "
            "VALUES (?, ?, 'created', ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, plan_version_id, run_scope, branch_id,
             int(force), requested_by, request_id, now, now, now),
        )
        return run_id

    def get(self, run_id: str) -> Run | None:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run(
            run_id=row["run_id"], plan_version_id=row["plan_version_id"],
            status=RunStatus(row["status"]), started_at=row["started_at"],
            finished_at=row["finished_at"], branch_id=row["branch_id"],
            force=bool(row["force"]),
        )

    def transition(self, run_id: str, to_status: RunStatus, *,
                   expected_from: tuple[RunStatus, ...] = (RunStatus.RUNNING,)) -> bool:
        from cardre.domain.run import _VALID_TRANSITIONS
        from cardre.domain.run import RunStatus as RS
        for s in expected_from:
            if to_status not in _VALID_TRANSITIONS.get(s, set()):
                raise ValueError(f"Invalid run state transition: {s!r} -> {to_status!r}")
        terminal = to_status in RS.terminal()
        placeholders = ", ".join("?" for _ in expected_from)
        if terminal:
            from cardre.domain.diagnostics import utc_now_iso
            now = utc_now_iso()
            cursor = self._conn.execute(
                f"UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ? AND status IN ({placeholders})",
                (to_status.value, now, run_id) + tuple(s.value for s in expected_from),
            )
        else:
            cursor = self._conn.execute(
                f"UPDATE runs SET status = ? WHERE run_id = ? AND status IN ({placeholders})",
                (to_status.value, run_id) + tuple(s.value for s in expected_from),
            )
        return bool(cursor.rowcount > 0)

    def heartbeat(self, run_id: str) -> None:
        from cardre.domain.diagnostics import utc_now_iso
        cursor = self._conn.execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ? AND status = 'running'",
            (utc_now_iso(), run_id),
        )
        if cursor.rowcount == 0:
            logger.warning("heartbeat: no running run found for run_id=%s", run_id)

    def set_active_step(self, run_id: str, step_id: str | None) -> None:
        self._conn.execute("UPDATE runs SET active_step_id = ? WHERE run_id = ?", (step_id, run_id))

    def get_active_step(self, run_id: str) -> str | None:
        row = self._conn.execute("SELECT active_step_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else row["active_step_id"]

    def set_cancel_requested(self, run_id: str) -> None:
        self._conn.execute("UPDATE runs SET cancel_requested = 1 WHERE run_id = ? AND status = 'running'", (run_id,))

    def append_diagnostic(self, run_id: str, diagnostic: dict[str, Any]) -> None:
        from cardre.domain.diagnostics import utc_now_iso
        extra = {k: v for k, v in diagnostic.items() if k not in {"code", "message", "source", "severity"}}
        self._conn.execute(
            "INSERT INTO diagnostics (diagnostic_id, run_id, code, message, source, severity, context_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, diagnostic.get("code", "UNKNOWN"), diagnostic.get("message", ""),
             diagnostic.get("source"), diagnostic.get("severity", "error"),
             json.dumps(extra), diagnostic.get("created_at", utc_now_iso())),
        )

    def get_diagnostics(self, run_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self._conn.execute(
            "SELECT * FROM diagnostics WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall():
            data = dict(row)
            ctx = json.loads(data.pop("context_json", "{}")) if data.get("context_json") else {}
            data.update(ctx)
            out.append(data)
        return out

    def list_for_plan_version(self, plan_version_id: str | None = None) -> list[Run]:
        if plan_version_id is None:
            rows = self._conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE plan_version_id = ? ORDER BY started_at DESC", (plan_version_id,)
            ).fetchall()
        return [Run(run_id=r["run_id"], plan_version_id=r["plan_version_id"],
                    status=RunStatus(r["status"]), started_at=r["started_at"],
                    finished_at=r["finished_at"], branch_id=r["branch_id"],
                    force=bool(r["force"])) for r in rows]

    def list_for_project(self, project_id: str) -> list[Run]:
        rows = self._conn.execute(
            "SELECT r.* FROM runs r JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id WHERE p.project_id = ? ORDER BY r.started_at DESC",
            (project_id,),
        ).fetchall()
        return [Run(run_id=r["run_id"], plan_version_id=r["plan_version_id"],
                    status=RunStatus(r["status"]), started_at=r["started_at"],
                    finished_at=r["finished_at"], branch_id=r["branch_id"],
                    force=bool(r["force"])) for r in rows]

    def get_latest_successful_id(self, plan_version_id: str, branch_id: str | None = None) -> str | None:
        clause, params = self._branch_filter(branch_id)
        row = self._conn.execute(
            f"SELECT run_id FROM runs WHERE plan_version_id = ? AND status = 'succeeded' {clause} ORDER BY started_at DESC LIMIT 1",
            [plan_version_id] + params,
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_id_for_plan(self, plan_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT r.run_id FROM runs r JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND r.status = 'succeeded' AND r.branch_id IS NULL ORDER BY r.started_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_step_across_plan(self, plan_id: str, step_id: str, branch_id: str | None = None) -> RunStep | None:
        clause, params = self._branch_filter(branch_id)
        row = self._conn.execute(
            "SELECT rs.* FROM run_steps rs JOIN runs r ON rs.run_id = r.run_id "
            "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND rs.step_id = ? AND rs.status = 'succeeded' AND r.status = 'succeeded' "
            f"{clause} ORDER BY rs.started_at DESC LIMIT 1",
            [plan_id, step_id] + params,
        ).fetchone()
        if row is None:
            return None
        return RunStep(
            run_step_id=row["run_step_id"], run_id=row["run_id"],
            step_id=row["step_id"], plan_version_id=row["plan_version_id"],
            status=RunStepStatus(row["status"]), started_at=row["started_at"],
            finished_at=row["finished_at"],
            execution_fingerprint=json.loads(row["execution_fingerprint_json"]),
            warnings=json.loads(row["warnings_json"]),
            errors=json.loads(row["errors_json"]),
        )

    def list_successful_steps_across_plan_ordered(
        self, plan_id: str, step_id: str, branch_id: str | None = None,
    ) -> list[RunStep]:
        """Return all successful run steps across all plan versions, newest-first."""
        clause, params = self._branch_filter(branch_id)
        rows = self._conn.execute(
            "SELECT rs.* FROM run_steps rs JOIN runs r ON rs.run_id = r.run_id "
            "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND rs.step_id = ? AND rs.status = 'succeeded' AND r.status = 'succeeded' "
            f"{clause} ORDER BY rs.started_at DESC, rs.run_step_id DESC",
            [plan_id, step_id] + params,
        ).fetchall()
        return [RunStep(
            run_step_id=r["run_step_id"], run_id=r["run_id"],
            step_id=r["step_id"], plan_version_id=r["plan_version_id"],
            status=RunStepStatus(r["status"]), started_at=r["started_at"],
            finished_at=r["finished_at"],
            execution_fingerprint=json.loads(r["execution_fingerprint_json"]),
            warnings=json.loads(r["warnings_json"]),
            errors=json.loads(r["errors_json"]),
        ) for r in rows]
