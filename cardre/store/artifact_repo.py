"""Artifact repository — artifact CRUD operations."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

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

    def list_for_project(
        self,
        project_id: str,
        *,
        role: str | None = None,
        artifact_type: str | None = None,
        producing_step_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ArtifactRef]:
        sql = (
            "SELECT DISTINCT a.* FROM artifacts a "
            "JOIN artifact_lineage al ON a.artifact_id = al.artifact_id AND al.direction = 'output' "
            "JOIN runs r ON al.run_id = r.run_id "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ?"
        )
        params: list[Any] = [project_id]
        if role is not None:
            sql += " AND a.role = ?"
            params.append(role)
        if artifact_type is not None:
            sql += " AND a.artifact_type = ?"
            params.append(artifact_type)
        if producing_step_id is not None:
            sql += " AND al.step_id = ?"
            params.append(producing_step_id)
        if run_id is not None:
            sql += " AND al.run_id = ?"
            params.append(run_id)
        sql += " ORDER BY a.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._db().execute(sql, params).fetchall()
        return [self._store._row_to_artifact_ref(r) for r in rows]
