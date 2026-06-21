"""Artifact repository — artifact CRUD operations."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from cardre.audit import ArtifactRef, utc_now_iso

if TYPE_CHECKING:
    from cardre.store.project_store import ProjectStore


class ArtifactRepository:
    """CRUD for artifacts within a ProjectStore."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def _db(self) -> sqlite3.Connection:
        return self._store._connect()

    def register(self, artifact: ArtifactRef) -> str:
        sql = """
            INSERT INTO artifacts
                (artifact_id, artifact_type, role, path, physical_hash,
                 logical_hash, media_type, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        now = utc_now_iso()
        with self._store.transaction() as conn:
            conn.execute(sql, (
                artifact.artifact_id,
                artifact.artifact_type,
                artifact.role,
                artifact.path,
                artifact.physical_hash,
                artifact.logical_hash,
                artifact.media_type,
                now,
                json.dumps(artifact.metadata),
            ))
        return artifact.artifact_id

    def get(self, artifact_id: str) -> ArtifactRef | None:
        row = self._db().execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return self._store._row_to_artifact_ref(row)

    def list(self) -> list[ArtifactRef]:
        rows = self._db().execute(
            "SELECT * FROM artifacts ORDER BY created_at"
        ).fetchall()
        return [self._store._row_to_artifact_ref(r) for r in rows]

    def list_for_project(self, project_id: str) -> list[ArtifactRef]:
        sql = (
            "SELECT DISTINCT a.* FROM artifacts a "
            "JOIN run_steps rs ON a.artifact_id IN ("
            "  SELECT value FROM json_each(rs.output_artifact_ids_json)"
            ") "
            "JOIN runs r ON rs.run_id = r.run_id "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? "
            "ORDER BY a.created_at DESC"
        )
        rows = self._db().execute(sql, (project_id,)).fetchall()
        return [self._store._row_to_artifact_ref(r) for r in rows]
