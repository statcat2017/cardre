"""SQLite project repository — query object for the projects table."""

from __future__ import annotations

import uuid
from typing import Any

from cardre.domain.project import Project


class ProjectRepo:
    """Query object for the projects table. Takes a connection, never commits."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def create(self, name: str) -> str:
        project_id = str(uuid.uuid4())
        from cardre._version import __version__
        from cardre.domain.diagnostics import utc_now_iso
        now = utc_now_iso()
        self._conn.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, name, now, __version__),
        )
        return project_id

    def get(self, project_id: str) -> Project | None:
        row = self._conn.execute(
            "SELECT project_id, name, created_at, cardre_version FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return Project(
            project_id=row["project_id"],
            name=row["name"],
            created_at=row["created_at"],
            cardre_version=row["cardre_version"],
        )

    def list_all(self) -> list[Project]:
        rows = self._conn.execute(
            "SELECT project_id, name, created_at, cardre_version FROM projects ORDER BY created_at"
        ).fetchall()
        return [
            Project(
                project_id=row["project_id"],
                name=row["name"],
                created_at=row["created_at"],
                cardre_version=row["cardre_version"],
            )
            for row in rows
        ]
