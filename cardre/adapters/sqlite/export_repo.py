"""SQLite exports repository — query object for the exports table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExportRecord:
    export_id: str
    run_id: str
    export_type: str
    path: str
    created_at: str
    size_bytes: int = 0


class ExportRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def register(self, export_id: str, run_id: str, export_type: str, path: str,
                 created_at: str, size_bytes: int = 0) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO exports (export_id, run_id, export_type, path, "
            "size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (export_id, run_id, export_type, path, size_bytes, created_at),
        )

    def list_for_project(self, project_id: str, run_id: str | None = None) -> list[ExportRecord]:
        sql = (
            "SELECT e.* FROM exports e JOIN runs r ON e.run_id = r.run_id "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id WHERE p.project_id = ? "
            "ORDER BY e.created_at"
        )
        params: list[Any] = [project_id]
        if run_id is not None:
            sql = (
                "SELECT e.* FROM exports e WHERE e.run_id = ? ORDER BY e.created_at"
            )
            params = [run_id]
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_export(r) for r in rows]

    def list_for_run(self, run_id: str) -> list[ExportRecord]:
        rows = self._conn.execute(
            "SELECT * FROM exports WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [_row_to_export(r) for r in rows]


def _row_to_export(r: Any) -> ExportRecord:
    return ExportRecord(
        export_id=r["export_id"], run_id=r["run_id"], export_type=r["export_type"],
        path=r["path"], created_at=r["created_at"],
        size_bytes=int(r["size_bytes"] or 0),
    )
