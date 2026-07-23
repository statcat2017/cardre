"""SQLite artifact repository — query object for artifacts and lineage."""

from __future__ import annotations

import json
import uuid
from typing import Any

from cardre.domain.artifacts import ArtifactRef


class ArtifactRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def register(self, artifact: ArtifactRef) -> str:
        existing = self._conn.execute(
            "SELECT artifact_id FROM artifacts WHERE physical_hash = ?", (artifact.physical_hash,)
        ).fetchone()
        if existing is not None:
            return str(existing["artifact_id"])
        from cardre.domain.diagnostics import utc_now_iso
        self._conn.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, storage_key, "
            "physical_hash, logical_hash, media_type, schema_version, created_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact.artifact_id, artifact.artifact_type, artifact.role,
             artifact.path, artifact.physical_hash, artifact.logical_hash,
             artifact.media_type,
             artifact.metadata.get("schema_version", ""),
             artifact.created_at or utc_now_iso(),
             json.dumps(artifact.metadata)),
        )
        return artifact.artifact_id

    def get(self, artifact_id: str) -> ArtifactRef | None:
        row = self._conn.execute(
            "SELECT artifact_id, artifact_type, role, storage_key, physical_hash, "
            "logical_hash, media_type, schema_version, created_at, metadata_json "
            "FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        if row["schema_version"]:
            metadata["schema_version"] = row["schema_version"]
        return ArtifactRef(
            artifact_id=row["artifact_id"], artifact_type=row["artifact_type"],
            role=row["role"], path=row["storage_key"],
            physical_hash=row["physical_hash"], logical_hash=row["logical_hash"],
            media_type=row["media_type"], created_at=row["created_at"],
            metadata=metadata,
        )

    def get_for_project(self, project_id: str, artifact_id: str) -> ArtifactRef | None:
        row = self._conn.execute(
            "SELECT a.* FROM artifacts a "
            "JOIN artifact_lineage al ON a.artifact_id = al.artifact_id "
            "JOIN runs r ON al.run_id = r.run_id "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? AND a.artifact_id = ? LIMIT 1",
            (project_id, artifact_id),
        ).fetchone()
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        if row["schema_version"]:
            metadata["schema_version"] = row["schema_version"]
        return ArtifactRef(
            artifact_id=row["artifact_id"], artifact_type=row["artifact_type"],
            role=row["role"], path=row["storage_key"],
            physical_hash=row["physical_hash"], logical_hash=row["logical_hash"],
            media_type=row["media_type"], created_at=row["created_at"],
            metadata=metadata,
        )

    def list_for_project(self, project_id: str, *, role: str | None = None,
                         artifact_type: str | None = None, limit: int = 100, offset: int = 0) -> list[ArtifactRef]:
        clauses = ["p.project_id = ?"]
        params: list[str] = [project_id]
        if role:
            clauses.append("a.role = ?")
            params.append(role)
        if artifact_type:
            clauses.append("a.artifact_type = ?")
            params.append(artifact_type)
        rows = self._conn.execute(
            f"SELECT DISTINCT a.* FROM artifacts a "
            f"JOIN artifact_lineage al ON a.artifact_id = al.artifact_id "
            f"JOIN runs r ON al.run_id = r.run_id "
            f"JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            f"JOIN plans p ON pv.plan_id = p.plan_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY a.created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        result = []
        for r in rows:
            metadata = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
            if r["schema_version"]:
                metadata["schema_version"] = r["schema_version"]
            result.append(ArtifactRef(
                artifact_id=r["artifact_id"], artifact_type=r["artifact_type"],
                role=r["role"], path=r["storage_key"],
                physical_hash=r["physical_hash"], logical_hash=r["logical_hash"],
                media_type=r["media_type"], created_at=r["created_at"],
                metadata=metadata,
            ))
        return result

    def register_lineage(self, run_id: str, run_step_id: str, plan_version_id: str,
                         step_id: str, artifact_id: str, direction: str, branch_id: str | None = None) -> None:
        from cardre.domain.diagnostics import utc_now_iso
        self._conn.execute(
            "INSERT OR IGNORE INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, "
            "step_id, branch_id, artifact_id, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, run_step_id, plan_version_id, step_id,
             branch_id, artifact_id, direction, utc_now_iso()),
        )

    def output_artifact_ids_for_run_step(self, run_step_id: str) -> list[str]:
        return [r["artifact_id"] for r in self._conn.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_step_id = ? AND direction = 'output'",
            (run_step_id,),
        ).fetchall()]

    def output_artifacts_for_run_step(self, run_step_id: str) -> list[ArtifactRef]:
        ids = self.output_artifact_ids_for_run_step(run_step_id)
        return [a for aid in ids if (a := self.get(aid)) is not None]

    def output_artifact_ids_for_run(self, run_id: str) -> list[str]:
        return [r["artifact_id"] for r in self._conn.execute(
            "SELECT artifact_id FROM artifact_lineage WHERE run_id = ? AND direction = 'output'",
            (run_id,),
        ).fetchall()]

    def artifacts_for_run_step(self, run_step_id: str) -> list[tuple[str, ArtifactRef]]:
        rows = self._conn.execute(
            "SELECT artifact_id, direction FROM artifact_lineage WHERE run_step_id = ? "
            "ORDER BY created_at, lineage_id",
            (run_step_id,),
        ).fetchall()
        return [
            (row["direction"], artifact)
            for row in rows
            if (artifact := self.get(row["artifact_id"])) is not None
        ]
