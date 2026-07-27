"""SQLite reports repository — query object for the reports table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    run_id: str | None
    report_type: str
    path: str
    created_at: str
    scope: str = "project"


class ReportRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def register(self, report_id: str, run_id: str | None, report_type: str,
                 path: str, created_at: str, scope: str = "project") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO reports (report_id, run_id, report_type, path, "
            "created_at, scope) VALUES (?, ?, ?, ?, ?, ?)",
            (report_id, run_id, report_type, path, created_at, scope),
        )

    def list_for_project(self, project_id: str) -> list[ReportRecord]:
        # Project-scoped reports: those whose run belongs to the project,
        # plus project-scope reports (run_id IS NULL) — for now only run-bound.
        rows = self._conn.execute(
            "SELECT r.* FROM reports r LEFT JOIN runs ru ON r.run_id = ru.run_id "
            "LEFT JOIN plan_versions pv ON ru.plan_version_id = pv.plan_version_id "
            "LEFT JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? OR r.run_id IS NULL "
            "ORDER BY r.created_at",
            (project_id,),
        ).fetchall()
        return [_row_to_report(r) for r in rows]

    def list_for_run(self, run_id: str) -> list[ReportRecord]:
        rows = self._conn.execute(
            "SELECT * FROM reports WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [_row_to_report(r) for r in rows]


def _row_to_report(r: Any) -> ReportRecord:
    return ReportRecord(
        report_id=r["report_id"], run_id=r["run_id"], report_type=r["report_type"],
        path=r["path"], created_at=r["created_at"], scope=r["scope"],
    )
