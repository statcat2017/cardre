"""SQLite run_step repository — query object for run_steps."""

from __future__ import annotations

import json
from typing import Any

from cardre.domain.run import RunStep, RunStepStatus


class RunStepRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def insert(self, conn: Any, run_step: RunStep) -> None:
        conn.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            "started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_step.run_step_id, run_step.run_id, run_step.step_id,
             run_step.plan_version_id, run_step.status.value,
             run_step.started_at, run_step.finished_at,
             json.dumps(run_step.execution_fingerprint),
             json.dumps(run_step.warnings), json.dumps(run_step.errors)),
        )

    def get(self, run_step_id: str) -> RunStep | None:
        row = self._conn.execute("SELECT * FROM run_steps WHERE run_step_id = ?", (run_step_id,)).fetchone()
        if row is None:
            return None
        return RunStep(
            run_step_id=row["run_step_id"], run_id=row["run_id"],
            step_id=row["step_id"], plan_version_id=row["plan_version_id"],
            status=RunStepStatus(row["status"]), started_at=row["started_at"],
            finished_at=row.get("finished_at"),
            execution_fingerprint=json.loads(row["execution_fingerprint_json"]),
            warnings=json.loads(row["warnings_json"]),
            errors=json.loads(row["errors_json"]),
        )

    def get_for_run(self, run_id: str) -> list[RunStep]:
        rows = self._conn.execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at, run_step_id",
            (run_id,),
        ).fetchall()
        return [RunStep(
            run_step_id=r["run_step_id"], run_id=r["run_id"],
            step_id=r["step_id"], plan_version_id=r["plan_version_id"],
            status=RunStepStatus(r["status"]), started_at=r["started_at"],
            finished_at=r.get("finished_at"),
            execution_fingerprint=json.loads(r["execution_fingerprint_json"]),
            warnings=json.loads(r["warnings_json"]),
            errors=json.loads(r["errors_json"]),
        ) for r in rows]

    def get_latest_successful_step(self, plan_version_id: str, step_id: str, branch_id: str | None = None) -> RunStep | None:
        clause = ""
        params: list = [plan_version_id, step_id]
        if branch_id is not None:
            clause = "AND r.branch_id = ?"
            params.append(branch_id)
        else:
            clause = "AND r.branch_id IS NULL"
        row = self._conn.execute(
            f"SELECT rs.* FROM run_steps rs JOIN runs r ON rs.run_id = r.run_id "
            f"WHERE rs.plan_version_id = ? AND rs.step_id = ? AND rs.status = 'succeeded' "
            f"{clause} ORDER BY rs.started_at DESC LIMIT 1",
            params,
        ).fetchone()
        if row is None:
            return None
        return RunStep(
            run_step_id=row["run_step_id"], run_id=row["run_id"],
            step_id=row["step_id"], plan_version_id=row["plan_version_id"],
            status=RunStepStatus(row["status"]), started_at=row["started_at"],
            finished_at=row.get("finished_at"),
            execution_fingerprint=json.loads(row["execution_fingerprint_json"]),
            warnings=json.loads(row["warnings_json"]),
            errors=json.loads(row["errors_json"]),
        )
