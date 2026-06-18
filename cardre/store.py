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


from cardre.store_schema import SCHEMA_SQL, BRANCH_TABLES_SQL


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

    def run_migrations(self) -> None:
        """Apply Phase 4 schema migrations to existing stores.

        Adds new columns and creates new tables for the branch model.
        Safe to call on fresh stores (idempotent).
        """
        conn = self._connect()
        conn.executescript(BRANCH_TABLES_SQL)

        # Add new columns to plan_steps if missing
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(plan_steps)").fetchall()}
        if "canonical_step_id" not in cols:
            conn.execute("ALTER TABLE plan_steps ADD COLUMN canonical_step_id TEXT NOT NULL DEFAULT ''")
        if "branch_id" not in cols:
            conn.execute("ALTER TABLE plan_steps ADD COLUMN branch_id TEXT")

        # Add branch_id to runs table if missing
        run_cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "branch_id" not in run_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN branch_id TEXT")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in ("datasets", "artifacts", "exports", "logs"):
            (self.root / sub).mkdir(exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
        self.run_migrations()

    def _connect(self) -> sqlite3.Connection:
        if self._db is not None:
            return self._db
        db_path = self.root / "cardre.sqlite"
        # check_same_thread=False allows the caller to manage thread
        # ownership; ProjectStore instances must NOT be shared across
        # worker threads without external synchronization.
        conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
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

    @staticmethod
    def _row_to_run_step(row: dict) -> RunStepRecord:
        return RunStepRecord(
            run_step_id=row["run_step_id"],
            run_id=row["run_id"],
            step_id=row["step_id"],
            plan_version_id=row["plan_version_id"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            input_artifact_ids=json.loads(row["input_artifact_ids_json"]),
            output_artifact_ids=json.loads(row["output_artifact_ids_json"]),
            execution_fingerprint=json.loads(row["execution_fingerprint_json"]),
            warnings=json.loads(row["warnings_json"]),
            errors=json.loads(row["errors_json"]),
        )

    @staticmethod
    def _row_to_artifact_ref(row: dict) -> ArtifactRef:
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
        return self._row_to_artifact_ref(row)

    def list_artifacts(self) -> list[ArtifactRef]:
        rows = self._connect().execute(
            "SELECT * FROM artifacts ORDER BY created_at"
        ).fetchall()
        return [self._row_to_artifact_ref(r) for r in rows]

    def list_artifacts_for_project(self, project_id: str) -> list[ArtifactRef]:
        sql = (
            "SELECT DISTINCT a.* FROM artifacts a "
            "JOIN run_steps rs ON a.artifact_id IN ("
            "  SELECT value FROM json_each(rs.output_artifact_ids_json)"
            ") "
            "JOIN runs r ON rs.run_id = r.run_id "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? "
            "ORDER BY a.created_at"
        )
        rows = self._connect().execute(sql, [project_id]).fetchall()
        return [self._row_to_artifact_ref(r) for r in rows]

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

    def _insert_plan_version_and_steps(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        steps: list[StepSpec],
        description: str = "",
    ) -> str:
        """Insert a plan version and its steps inside an open transaction."""
        plan_version_id = str(uuid.uuid4())
        now = utc_now_iso()
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
                " params_json, params_hash, parent_step_ids_json, branch_label, position, "
                " canonical_step_id, branch_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    step.canonical_step_id,
                    step.branch_id,
                ),
            )
        return plan_version_id

    def create_plan_version(
        self,
        plan_id: str,
        steps: list[StepSpec],
        description: str = "",
    ) -> str:
        with self.transaction() as conn:
            return self._insert_plan_version_and_steps(conn, plan_id, steps, description)

    def create_plan_version_in_transaction(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        steps: list[StepSpec],
        description: str = "",
    ) -> str:
        """Create a new plan version inside an existing transaction.

        Useful for atomic branch creation where plan version, branch
        metadata, and branch step maps must be committed together.
        """
        return self._insert_plan_version_and_steps(conn, plan_id, steps, description)

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
        if not rows:
            return []
        col_names = rows[0].keys()
        has_canonical = "canonical_step_id" in col_names
        has_branch = "branch_id" in col_names
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
                canonical_step_id=r["canonical_step_id"] if has_canonical else r["step_id"],
                branch_id=r["branch_id"] if has_branch else None,
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

    def list_plan_versions(self, plan_id: str) -> list[JsonDict]:
        rows = self._connect().execute(
            "SELECT * FROM plan_versions WHERE plan_id = ? ORDER BY version_number",
            (plan_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def create_branch(
        self,
        project_id: str,
        plan_id: str,
        name: str,
        branch_type: str,
        base_plan_version_id: str,
        head_plan_version_id: str,
        created_reason: str,
        branch_id: str | None = None,
        description: str | None = None,
        base_branch_id: str | None = None,
        branch_point_step_id: str | None = None,
        branch_point_canonical_step_id: str | None = None,
        segment_filter_spec_json: str | None = None,
    ) -> str:
        bid = branch_id or str(uuid.uuid4())
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO plan_branches "
                "(branch_id, project_id, plan_id, name, description, branch_type, status, "
                " base_branch_id, base_plan_version_id, head_plan_version_id, "
                " branch_point_step_id, branch_point_canonical_step_id, "
                " segment_filter_spec_json, created_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bid, project_id, plan_id, name, description, branch_type,
                    base_branch_id, base_plan_version_id, head_plan_version_id,
                    branch_point_step_id, branch_point_canonical_step_id,
                    segment_filter_spec_json, created_reason, now, now,
                ),
            )
        return bid

    def get_branch(self, branch_id: str) -> JsonDict | None:
        row = self._connect().execute(
            "SELECT * FROM plan_branches WHERE branch_id = ?", (branch_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def list_branches(
        self,
        project_id: str,
        plan_id: str | None = None,
        branch_type: str | None = None,
        status: str | None = None,
    ) -> list[JsonDict]:
        sql = "SELECT * FROM plan_branches WHERE project_id = ?"
        params: list[Any] = [project_id]
        if plan_id is not None:
            sql += " AND plan_id = ?"
            params.append(plan_id)
        if branch_type is not None:
            sql += " AND branch_type = ?"
            params.append(branch_type)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at"
        rows = self._connect().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update_branch_head(
        self,
        branch_id: str,
        head_plan_version_id: str,
    ) -> None:
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE plan_branches SET head_plan_version_id = ?, updated_at = ? WHERE branch_id = ?",
                (head_plan_version_id, now, branch_id),
            )

    def create_branch_step_map(
        self,
        branch_id: str,
        plan_version_id: str,
        canonical_step_id: str,
        step_id: str,
        is_shared_upstream: bool = False,
        is_branch_owned: bool = True,
        source_branch_id: str | None = None,
        source_step_id: str | None = None,
    ) -> str:
        map_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO branch_step_map "
                "(branch_step_map_id, branch_id, plan_version_id, canonical_step_id, step_id, "
                " source_branch_id, source_step_id, is_shared_upstream, is_branch_owned, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    map_id, branch_id, plan_version_id, canonical_step_id, step_id,
                    source_branch_id, source_step_id,
                    1 if is_shared_upstream else 0,
                    1 if is_branch_owned else 0,
                    now,
                ),
            )
        return map_id

    def get_branch_step_map(
        self,
        branch_id: str,
        plan_version_id: str | None = None,
    ) -> list[JsonDict]:
        if plan_version_id is not None:
            rows = self._connect().execute(
                "SELECT * FROM branch_step_map WHERE branch_id = ? AND plan_version_id = ?",
                (branch_id, plan_version_id),
            ).fetchall()
        else:
            rows = self._connect().execute(
                "SELECT * FROM branch_step_map WHERE branch_id = ?",
                (branch_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Runs / Run Steps
    # ------------------------------------------------------------------

    def create_run(self, plan_version_id: str, branch_id: str | None = None) -> str:
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, plan_version_id, status, started_at, branch_id) VALUES (?, ?, ?, ?, ?)",
                (run_id, plan_version_id, "running", now, branch_id),
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
        return [self._row_to_run_step(r) for r in rows]

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

    def get_latest_successful_run_id(
        self,
        plan_version_id: str,
        branch_id: str | None = None,
    ) -> str | None:
        if branch_id:
            row = self._connect().execute(
                "SELECT run_id FROM runs WHERE plan_version_id = ? AND branch_id = ? AND status = 'succeeded' "
                "ORDER BY started_at DESC LIMIT 1",
                (plan_version_id, branch_id),
            ).fetchone()
        else:
            row = self._connect().execute(
                "SELECT run_id FROM runs WHERE plan_version_id = ? AND branch_id IS NULL AND status = 'succeeded' "
                "ORDER BY started_at DESC LIMIT 1",
                (plan_version_id,),
            ).fetchone()
        return None if row is None else row["run_id"]

    def get_latest_successful_run_id_for_plan(self, plan_id: str) -> str | None:
        """Return the most recent successful run_id across all versions of a plan."""
        row = self._connect().execute(
            "SELECT r.run_id FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND r.status = 'succeeded' AND r.branch_id IS NULL "
            "ORDER BY r.started_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_run_step(self, run_step_id: str) -> RunStepRecord | None:
        row = self._connect().execute(
            "SELECT * FROM run_steps WHERE run_step_id = ?",
            (run_step_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run_step(row)

    def get_latest_successful_run_step_for_step(
        self,
        plan_version_id: str,
        step_id: str,
        branch_id: str | None = None,
    ) -> RunStepRecord | None:
        if branch_id:
            row = self._connect().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "WHERE rs.plan_version_id = ? AND rs.step_id = ? "
                "AND r.branch_id = ? AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_version_id, step_id, branch_id),
            ).fetchone()
        else:
            row = self._connect().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "WHERE rs.plan_version_id = ? AND rs.step_id = ? "
                "AND r.branch_id IS NULL AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_version_id, step_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_run_step(row)

    def get_latest_successful_run_step_for_step_across_plan(
        self,
        plan_id: str,
        step_id: str,
        branch_id: str | None = None,
    ) -> RunStepRecord | None:
        if branch_id:
            row = self._connect().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
                "WHERE pv.plan_id = ? AND rs.step_id = ? "
                "AND r.branch_id = ? AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_id, step_id, branch_id),
            ).fetchone()
        else:
            row = self._connect().execute(
                "SELECT rs.* FROM run_steps rs "
                "JOIN runs r ON rs.run_id = r.run_id "
                "JOIN plan_versions pv ON rs.plan_version_id = pv.plan_version_id "
                "WHERE pv.plan_id = ? AND rs.step_id = ? "
                "AND r.branch_id IS NULL AND rs.status = 'succeeded' "
                "ORDER BY rs.started_at DESC LIMIT 1",
                (plan_id, step_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_run_step(row)

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
            "SELECT r.*, COALESCE(rs.step_count, 0) AS step_count FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "LEFT JOIN (SELECT run_id, COUNT(*) AS step_count FROM run_steps GROUP BY run_id) rs "
            "  ON r.run_id = rs.run_id "
            "WHERE p.project_id = ? "
            "ORDER BY r.started_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Champion assignments
    # ------------------------------------------------------------------

    def get_champion_assignment(self, plan_id: str, champion_branch_id: str | None = None) -> dict | None:
        """Get the current champion assignment for a plan, optionally filtered by branch."""
        if champion_branch_id:
            row = self._connect().execute(
                "SELECT * FROM champion_assignments "
                "WHERE plan_id = ? AND champion_branch_id = ? AND superseded_at IS NULL "
                "ORDER BY assigned_at DESC LIMIT 1",
                (plan_id, champion_branch_id),
            ).fetchone()
        else:
            row = self._connect().execute(
                "SELECT * FROM champion_assignments "
                "WHERE plan_id = ? AND superseded_at IS NULL "
                "ORDER BY assigned_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
        return None if row is None else dict(row)

    # ------------------------------------------------------------------
    # Branch comparisons
    # ------------------------------------------------------------------

    def get_branch_comparison(self, comparison_id: str) -> JsonDict | None:
        row = self._connect().execute(
            "SELECT * FROM branch_comparisons WHERE comparison_id = ?",
            (comparison_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshot(self, snapshot_id: str) -> JsonDict | None:
        row = self._connect().execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_comparison_snapshots_for_comparison(self, comparison_id: str) -> list[JsonDict]:
        rows = self._connect().execute(
            "SELECT * FROM branch_comparison_snapshots WHERE comparison_id = ? ORDER BY created_at DESC",
            (comparison_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_champion_assignment_by_branch(self, branch_id: str) -> dict | None:
        row = self._connect().execute(
            "SELECT * FROM champion_assignments "
            "WHERE champion_branch_id = ? AND superseded_at IS NULL "
            "ORDER BY assigned_at DESC LIMIT 1",
            (branch_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def get_plan_version_ids_for_branch(self, branch_id: str) -> list[str]:
        rows = self._connect().execute(
            "SELECT DISTINCT plan_version_id FROM branch_step_map WHERE branch_id = ?",
            (branch_id,),
        ).fetchall()
        return [r["plan_version_id"] for r in rows]

    def get_any_successful_run_id_for_plan(self, plan_id: str) -> str | None:
        row = self._connect().execute(
            "SELECT r.run_id FROM runs r "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "WHERE pv.plan_id = ? AND r.status = 'succeeded' "
            "ORDER BY r.started_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return None if row is None else row["run_id"]

    def get_output_artifact_ids_for_branch(self, branch_id: str) -> list[list[str]]:
        rows = self._connect().execute(
            "SELECT rs.output_artifact_ids_json FROM run_steps rs "
            "JOIN runs r ON rs.run_id = r.run_id "
            "WHERE r.branch_id = ? AND rs.status = 'succeeded' "
            "ORDER BY rs.started_at DESC",
            (branch_id,),
        ).fetchall()
        return [json.loads(r["output_artifact_ids_json"]) for r in rows if r["output_artifact_ids_json"]]

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
            ("plan_branches", "segment_filter_spec_json"),
            ("branch_comparisons", "challenger_branch_ids_json"),
            ("branch_comparisons", "comparison_spec_json"),
            ("branch_comparisons", "latest_readiness_json"),
            ("branch_comparison_snapshots", "readiness_json"),
            ("branch_comparison_snapshots", "source_plan_version_ids_json"),
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
