"""Artifact repository — CRUD for artifacts and artifact_lineage."""

from __future__ import annotations

import builtins
import json
import uuid
from typing import TYPE_CHECKING, Any

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso

if TYPE_CHECKING:
    from cardre.store.db import ProjectStore


class ArtifactRepository:
    """Repository for artifacts."""

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def register(self, artifact: ArtifactRef) -> str:
        self._store.execute(
            "INSERT INTO artifacts "
            "(artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact.artifact_id,
                artifact.artifact_type,
                artifact.role,
                artifact.path,
                artifact.physical_hash,
                artifact.logical_hash,
                artifact.media_type,
                artifact.created_at,
                json.dumps(artifact.metadata),
            ),
        )
        return artifact.artifact_id

    def get(self, artifact_id: str) -> ArtifactRef | None:
        row = self._store.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_artifact_ref(row)

    def list(self) -> list[ArtifactRef]:
        rows = self._store.execute("SELECT * FROM artifacts ORDER BY created_at").fetchall()
        return [self._row_to_artifact_ref(r) for r in rows]

    def get_for_project(self, project_id: str, artifact_id: str) -> ArtifactRef | None:
        row = self._store.execute(
            "SELECT DISTINCT a.* FROM artifacts a "
            "JOIN artifact_lineage al ON al.artifact_id = a.artifact_id "
            "JOIN plan_versions pv ON al.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? AND a.artifact_id = ?",
            (project_id, artifact_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_artifact_ref(row)

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
    ) -> builtins.list[ArtifactRef]:
        sql = [
            "SELECT DISTINCT a.* FROM artifacts a",
            "JOIN artifact_lineage al ON al.artifact_id = a.artifact_id",
            "JOIN plan_versions pv ON al.plan_version_id = pv.plan_version_id",
            "JOIN plans p ON pv.plan_id = p.plan_id",
            "WHERE p.project_id = ?",
        ]
        params: list[object] = [project_id]
        if role is not None:
            sql.append("AND a.role = ?")
            params.append(role)
        if artifact_type is not None:
            sql.append("AND a.artifact_type = ?")
            params.append(artifact_type)
        if producing_step_id is not None:
            sql.append("AND al.step_id = ?")
            params.append(producing_step_id)
        if run_id is not None:
            sql.append("AND al.run_id = ?")
            params.append(run_id)
        sql.append("ORDER BY a.created_at LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        rows = self._store.execute(" ".join(sql), tuple(params)).fetchall()
        return [self._row_to_artifact_ref(r) for r in rows]

    def register_lineage(
        self,
        run_id: str,
        run_step_id: str,
        plan_version_id: str,
        step_id: str,
        artifact_id: str,
        direction: str,
        branch_id: str | None = None,
    ) -> str:
        lineage_id = str(uuid.uuid4())
        now = utc_now_iso()
        self._store.execute(
            "INSERT OR IGNORE INTO artifact_lineage "
            "(lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (lineage_id, run_id, run_step_id, plan_version_id, step_id, branch_id, artifact_id, direction, now),
        )
        return lineage_id

    def get_lineage_for_run_step(self, run_step_id: str) -> builtins.list[dict[str, Any]]:
        rows = self._store.execute(
            "SELECT * FROM artifact_lineage WHERE run_step_id = ? ORDER BY direction, created_at",
            (run_step_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_to_artifact_ref(row: dict[str, Any]) -> ArtifactRef:
        d = dict(row)
        return ArtifactRef(
            artifact_id=d["artifact_id"],
            artifact_type=d["artifact_type"],
            role=d["role"],
            path=d["path"],
            physical_hash=d["physical_hash"],
            logical_hash=d["logical_hash"],
            media_type=d["media_type"],
            created_at=d["created_at"],
            metadata=json.loads(d.get("metadata_json", "{}")),
        )
