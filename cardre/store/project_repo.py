"""Project repository — query-only CRUD for the ``projects`` table."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from cardre.domain.diagnostics import JsonDict, utc_now_iso

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class ProjectRepository:
    """Repository for project metadata."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def create(self, name: str, cardre_version: str = "0.2.0") -> str:
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, name, now, cardre_version),
        )
        return project_id

    def get(self, project_id: str) -> JsonDict | None:
        row = self._store.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
        return d

    def list_all(self) -> list[JsonDict]:
        rows = self._store.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]
