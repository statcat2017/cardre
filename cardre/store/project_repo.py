"""Project repository — project CRUD."""

from __future__ import annotations

import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

from cardre.audit import utc_now_iso

if TYPE_CHECKING:
    from cardre.store.project_store import ProjectStore


class ProjectRepository:
    """CRUD for projects."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _db(self) -> sqlite3.Connection:
        return self._store._connect()

    def create(self, name: str, cardre_version: str = "0.1.0") -> str:
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self._store.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
                (project_id, name, now, cardre_version),
            )
        return project_id

    def get(self, project_id: str) -> dict[str, Any] | None:
        row = self._db().execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)
