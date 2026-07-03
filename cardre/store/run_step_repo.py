"""Run-step repository — CRUD for run_steps (no artifact ID arrays)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from cardre.domain.run import RunStep, RunStepStatus

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class RunStepRepository:
    """Repository for run steps."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def save(self, run_step: RunStep) -> None:
        self._store.execute(
            "INSERT INTO run_steps "
            "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
            " execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_step.run_step_id,
                run_step.run_id,
                run_step.step_id,
                run_step.plan_version_id,
                run_step.status.value,
                run_step.started_at,
                run_step.finished_at,
                json.dumps(run_step.execution_fingerprint),
                json.dumps(run_step.warnings),
                json.dumps(run_step.errors),
            ),
        )

    def get(self, run_step_id: str) -> RunStep | None:
        row = self._store.execute(
            "SELECT * FROM run_steps WHERE run_step_id = ?", (run_step_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run_step(row)

    def get_for_run(self, run_id: str) -> list[RunStep]:
        rows = self._store.execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at",
            (run_id,),
        ).fetchall()
        return [self._row_to_run_step(r) for r in rows]

    def get_latest_successful_step(
        self,
        plan_version_id: str,
        step_id: str,
        branch_id: str | None = None,
    ) -> RunStep | None:
        if branch_id:
            row = self._store.execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "WHERE rs.plan_version_id = ? AND rs.step_id = ? AND r.branch_id = ? "
                "AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_version_id, step_id, branch_id),
            ).fetchone()
        else:
            row = self._store.execute(
                "SELECT * FROM run_steps WHERE plan_version_id = ? AND step_id = ? "
                "AND status = 'succeeded' ORDER BY started_at DESC LIMIT 1",
                (plan_version_id, step_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_run_step(row)

    @staticmethod
    def _row_to_run_step(row) -> RunStep:
        d = dict(row)
        return RunStep(
            run_step_id=d["run_step_id"],
            run_id=d["run_id"],
            step_id=d["step_id"],
            plan_version_id=d["plan_version_id"],
            status=RunStepStatus(d["status"]),
            started_at=d["started_at"],
            finished_at=d.get("finished_at"),
            execution_fingerprint=json.loads(d["execution_fingerprint_json"]),
            warnings=json.loads(d.get("warnings_json", "[]")),
            errors=json.loads(d.get("errors_json", "[]")),
        )
