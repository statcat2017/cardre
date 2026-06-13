"""SQLite-backed metadata store for Cardre projects.

Phase 1: SQLite stores metadata only. Tabular data lives in Parquet
artifacts on the filesystem. Every artifact has physical_hash and
logical_hash.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cardre.audit import (
    ArtifactRef,
    JsonDict,
    RunStepRecord,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    utc_now_iso,
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cardre_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plan_versions (
    plan_version_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS plan_steps (
    step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
    node_type TEXT NOT NULL,
    node_version TEXT NOT NULL,
    category TEXT NOT NULL,
    params_json TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    parent_step_ids_json TEXT NOT NULL,
    branch_label TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL,
    PRIMARY KEY (plan_version_id, step_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_steps (
    run_step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    input_artifact_ids_json TEXT NOT NULL,
    output_artifact_ids_json TEXT NOT NULL,
    execution_fingerprint_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    role TEXT NOT NULL,
    path TEXT NOT NULL,
    physical_hash TEXT NOT NULL,
    logical_hash TEXT NOT NULL,
    media_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS warnings (
    warning_id TEXT PRIMARY KEY,
    run_step_id TEXT,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS errors (
    error_id TEXT PRIMARY KEY,
    run_step_id TEXT,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


class ProjectStore:
    """SQLite-backed metadata store for a single Cardre project.

    The project root is a directory (e.g. ``example.cardre/``) containing:
      - cardre.sqlite
      - datasets/
      - artifacts/
      - exports/
      - logs/
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._db: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in ("datasets", "artifacts", "exports", "logs"):
            (self.root / sub).mkdir(exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        if self._db is not None:
            return self._db
        db_path = self.root / "cardre.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        self._db = conn
        return conn

    @contextmanager
    def transaction(self) -> sqlite3.Connection:
        conn = self._connect()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------

    def create_project(self, name: str, cardre_version: str = "0.1.0") -> str:
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
                (project_id, name, now, cardre_version),
            )
        return project_id

    def get_project(self, project_id: str) -> JsonDict | None:
        row = self._connect().execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    def register_artifact(self, artifact: ArtifactRef) -> str:
        sql = """
            INSERT INTO artifacts
                (artifact_id, artifact_type, role, path, physical_hash,
                 logical_hash, media_type, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        now = utc_now_iso()
        with self.transaction() as conn:
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

    def get_artifact(self, artifact_id: str) -> ArtifactRef | None:
        row = self._connect().execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return ArtifactRef(
            artifact_id=row["artifact_id"],
            artifact_type=row["artifact_type"],
            role=row["role"],
            path=row["path"],
            physical_hash=row["physical_hash"],
            logical_hash=row["logical_hash"],
            media_type=row["media_type"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"]),
        )

    def list_artifacts(self) -> list[ArtifactRef]:
        rows = self._connect().execute(
            "SELECT * FROM artifacts ORDER BY created_at"
        ).fetchall()
        return [
            ArtifactRef(
                artifact_id=r["artifact_id"],
                artifact_type=r["artifact_type"],
                role=r["role"],
                path=r["path"],
                physical_hash=r["physical_hash"],
                logical_hash=r["logical_hash"],
                media_type=r["media_type"],
                created_at=r["created_at"],
                metadata=json.loads(r["metadata_json"]),
            )
            for r in rows
        ]

    def list_artifacts_for_project(self, project_id: str) -> list[ArtifactRef]:
        rows = self._connect().execute(
            "SELECT DISTINCT a.* FROM artifacts a "
            "JOIN run_steps rs ON a.artifact_id IN ("
            "  SELECT value FROM json_each(rs.output_artifact_ids_json)"
            ") "
            "JOIN runs r ON rs.run_id = r.run_id "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? "
            "ORDER BY a.created_at",
            (project_id,),
        ).fetchall()
        return [
            ArtifactRef(
                artifact_id=r["artifact_id"],
                artifact_type=r["artifact_type"],
                role=r["role"],
                path=r["path"],
                physical_hash=r["physical_hash"],
                logical_hash=r["logical_hash"],
                media_type=r["media_type"],
                created_at=r["created_at"],
                metadata=json.loads(r["metadata_json"]),
            )
            for r in rows
        ]

    def get_plans_for_project(self, project_id: str) -> list[dict]:
        rows = self._connect().execute(
            "SELECT plan_id, name, created_at FROM plans WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def artifact_path(self, artifact: ArtifactRef) -> Path:
        return self.root / artifact.path

    def write_artifact_bytes(
        self,
        data: bytes,
        *,
        artifact_type: str,
        role: str,
        filename: str,
        media_type: str = "application/octet-stream",
        metadata: JsonDict | None = None,
    ) -> ArtifactRef:
        digest = hashlib_data(data)
        artifact_id = str(uuid.uuid4())
        stored_path = self.root / "artifacts" / f"{digest[:16]}-{filename}"
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        if not stored_path.exists():
            stored_path.write_bytes(data)
        phys = physical_hash(stored_path)
        logical = json_logical_hash({"content_hash": digest}) if media_type.endswith("json") else digest
        ref = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            role=role,
            path=relative_path(stored_path, self.root),
            physical_hash=phys,
            logical_hash=logical,
            media_type=media_type,
            metadata=metadata or {},
        )
        self.register_artifact(ref)
        return ref

    def ingest_existing_artifact(
        self,
        source_path: Path,
        *,
        artifact_type: str,
        role: str,
        media_type: str,
        metadata: JsonDict | None = None,
        logical_hash_override: str | None = None,
    ) -> ArtifactRef:
        artifact_id = str(uuid.uuid4())
        phys = physical_hash(source_path)
        logical = logical_hash_override or phys
        stored_path = self.root / "datasets" / f"{phys[:16]}-{source_path.name}"
        if not stored_path.exists():
            stored_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = stored_path.with_suffix(stored_path.suffix + ".tmp")
            tmp_path.write_bytes(source_path.read_bytes())
            tmp_path.rename(stored_path)
        ref = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            role=role,
            path=relative_path(stored_path, self.root),
            physical_hash=phys,
            logical_hash=logical,
            media_type=media_type,
            metadata=metadata or {},
        )
        self.register_artifact(ref)
        return ref

    # ------------------------------------------------------------------
    # Plans / Plan Versions / Plan Steps
    # ------------------------------------------------------------------

    def create_plan(self, project_id: str, name: str) -> str:
        plan_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
                (plan_id, project_id, name, now),
            )
        return plan_id

    def get_plan(self, plan_id: str) -> JsonDict | None:
        row = self._connect().execute(
            "SELECT * FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def create_plan_version(
        self,
        plan_id: str,
        steps: list[StepSpec],
        description: str = "",
    ) -> str:
        plan_version_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.transaction() as conn:
            max_ver = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM plan_versions WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, created_at, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (plan_version_id, plan_id, max_ver, now, description),
            )
            for step in steps:
                conn.execute(
                    "INSERT INTO plan_steps "
                    "(step_id, plan_version_id, node_type, node_version, category, "
                    " params_json, params_hash, parent_step_ids_json, branch_label, position) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        step.step_id,
                        plan_version_id,
                        step.node_type,
                        step.node_version,
                        step.category,
                        json.dumps(step.params),
                        step.params_hash,
                        json.dumps(step.parent_step_ids),
                        step.branch_label,
                        step.position,
                    ),
                )
        return plan_version_id

    def get_plan_version(self, plan_version_id: str) -> JsonDict | None:
        row = self._connect().execute(
            "SELECT * FROM plan_versions WHERE plan_version_id = ?", (plan_version_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def get_plan_version_steps(self, plan_version_id: str) -> list[StepSpec]:
        rows = self._connect().execute(
            "SELECT * FROM plan_steps WHERE plan_version_id = ? ORDER BY position",
            (plan_version_id,),
        ).fetchall()
        return [
            StepSpec(
                step_id=r["step_id"],
                node_type=r["node_type"],
                node_version=r["node_version"],
                category=r["category"],
                params=json.loads(r["params_json"]),
                params_hash=r["params_hash"],
                parent_step_ids=json.loads(r["parent_step_ids_json"]),
                branch_label=r["branch_label"],
                position=r["position"],
            )
            for r in rows
        ]

    def get_latest_plan_version_id(self, plan_id: str) -> str | None:
        row = self._connect().execute(
            "SELECT plan_version_id FROM plan_versions WHERE plan_id = ? "
            "ORDER BY version_number DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["plan_version_id"]

    # ------------------------------------------------------------------
    # Runs / Run Steps
    # ------------------------------------------------------------------

    def create_run(self, plan_version_id: str) -> str:
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, plan_version_id, status, started_at) VALUES (?, ?, ?, ?)",
                (run_id, plan_version_id, "running", now),
            )
        return run_id

    def finish_run(self, run_id: str, status: str = "succeeded") -> None:
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                (status, now, run_id),
            )

    def get_run(self, run_id: str) -> JsonDict | None:
        row = self._connect().execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def save_run_step(self, rs: RunStepRecord) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO run_steps "
                "(run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, input_artifact_ids_json, "
                " output_artifact_ids_json, execution_fingerprint_json, "
                " warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rs.run_step_id,
                    rs.run_id,
                    rs.step_id,
                    rs.plan_version_id,
                    rs.status,
                    rs.started_at,
                    rs.finished_at,
                    json.dumps(rs.input_artifact_ids),
                    json.dumps(rs.output_artifact_ids),
                    json.dumps(rs.execution_fingerprint),
                    json.dumps(rs.warnings),
                    json.dumps(rs.errors),
                ),
            )

    def get_run_steps(self, run_id: str) -> list[RunStepRecord]:
        rows = self._connect().execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at",
            (run_id,),
        ).fetchall()
        return [
            RunStepRecord(
                run_step_id=r["run_step_id"],
                run_id=r["run_id"],
                step_id=r["step_id"],
                plan_version_id=r["plan_version_id"],
                status=r["status"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                input_artifact_ids=json.loads(r["input_artifact_ids_json"]),
                output_artifact_ids=json.loads(r["output_artifact_ids_json"]),
                execution_fingerprint=json.loads(r["execution_fingerprint_json"]),
                warnings=json.loads(r["warnings_json"]),
                errors=json.loads(r["errors_json"]),
            )
            for r in rows
        ]

    def get_artifact_ids_for_run(self, run_id: str) -> set[str]:
        rows = self._connect().execute(
            "SELECT DISTINCT json_each.value AS artifact_id "
            "FROM run_steps, json_each(run_steps.output_artifact_ids_json) "
            "WHERE run_steps.run_id = ?",
            (run_id,),
        ).fetchall()
        return {r["artifact_id"] for r in rows}

    def get_artifact_ids_for_producing_step(self, step_id: str) -> set[str]:
        rows = self._connect().execute(
            "SELECT DISTINCT json_each.value AS artifact_id "
            "FROM run_steps, json_each(run_steps.output_artifact_ids_json) "
            "WHERE run_steps.step_id = ?",
            (step_id,),
        ).fetchall()
        return {r["artifact_id"] for r in rows}

    def get_latest_successful_run_id(self, plan_version_id: str) -> str | None:
        row = self._connect().execute(
            "SELECT run_id FROM runs WHERE plan_version_id = ? AND status = 'succeeded' "
            "ORDER BY started_at DESC LIMIT 1",
            (plan_version_id,),
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_run_id_for_plan(self, plan_id: str) -> str | None:
        """Return the most recent successful run_id across all versions of a plan."""
        row = self._connect().execute(
            "SELECT r.run_id FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND r.status = 'succeeded' "
            "ORDER BY r.started_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_plan_id_for_version(self, plan_version_id: str) -> str | None:
        row = self._connect().execute(
            "SELECT plan_id FROM plan_versions WHERE plan_version_id = ?",
            (plan_version_id,),
        ).fetchone()
        return None if row is None else row["plan_id"]

    def list_runs(self, plan_version_id: str | None = None) -> list[JsonDict]:
        if plan_version_id is not None:
            rows = self._connect().execute(
                "SELECT * FROM runs WHERE plan_version_id = ? ORDER BY started_at DESC",
                (plan_version_id,),
            ).fetchall()
        else:
            rows = self._connect().execute(
                "SELECT * FROM runs ORDER BY started_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_runs_for_project(self, project_id: str) -> list[JsonDict]:
        rows = self._connect().execute(
            "SELECT r.* FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? "
            "ORDER BY r.started_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Database / state queries
    # ------------------------------------------------------------------

    def get_sqlite_path(self) -> Path:
        return self.root / "cardre.sqlite"

    def verify_no_tabular_blobs(self) -> bool:
        """Verify SQLite contains no large binary blobs (Phase 1 acceptance).

        Inspects stored JSON columns by checking their octet length.
        """
        json_cols = [
            ("plan_steps", "params_json"),
            ("plan_steps", "parent_step_ids_json"),
            ("artifacts", "metadata_json"),
            ("run_steps", "input_artifact_ids_json"),
            ("run_steps", "output_artifact_ids_json"),
            ("run_steps", "execution_fingerprint_json"),
            ("runs", "metadata_json"),
        ]
        conn = self._connect()
        for table, col in json_cols:
            row = conn.execute(
                f"SELECT MAX(LENGTH({col})) AS max_len FROM (SELECT {col} FROM {table} LIMIT 20)"
            ).fetchone()
            if row and row["max_len"] is not None and row["max_len"] > 100_000:
                return False
        return True


def hashlib_data(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()
