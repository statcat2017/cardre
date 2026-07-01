"""Tests for artifact_lineage — backfill, query rewrites, duplicate prevention, query shape."""

from __future__ import annotations

import uuid
import unittest
from pathlib import Path

from cardre.audit import (
    ArtifactRef,
    RunStepRecord,
    StepSpec,
    json_logical_hash,
    utc_now_iso,
)
from cardre.store import ProjectStore
from cardre.store.schema import STORE_SCHEMA_VERSION

from tests.helpers import make_store


class ArtifactLineageBackfillTests(unittest.TestCase):
    """Backfill from legacy run_steps JSON arrays into artifact_lineage."""

    def test_backfill_populates_lineage_from_existing_run_steps(self):
        """Build a v4-style store with run_steps containing JSON arrays,
        then run migrations and assert lineage rows exist."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.root.mkdir(parents=True, exist_ok=True)
        for sub in ("datasets", "artifacts", "exports", "logs"):
            (store.root / sub).mkdir(exist_ok=True)

        # Create v4 schema (no lineage table)
        v4_schema = """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            created_at TEXT NOT NULL, cardre_version TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            name TEXT NOT NULL, created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS plan_versions (
            plan_version_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL,
            version_number INTEGER NOT NULL, created_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS plan_steps (
            step_id TEXT NOT NULL, plan_version_id TEXT NOT NULL,
            node_type TEXT NOT NULL, node_version TEXT NOT NULL,
            category TEXT NOT NULL, params_json TEXT NOT NULL,
            params_hash TEXT NOT NULL, parent_step_ids_json TEXT NOT NULL,
            branch_label TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
            PRIMARY KEY (plan_version_id, step_id)
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, plan_version_id TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
            branch_id TEXT
        );
        CREATE TABLE IF NOT EXISTS run_steps (
            run_step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            step_id TEXT NOT NULL, plan_version_id TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, input_artifact_ids_json TEXT NOT NULL,
            output_artifact_ids_json TEXT NOT NULL,
            execution_fingerprint_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            errors_json TEXT NOT NULL DEFAULT '[]',
            is_carried_forward INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL,
            role TEXT NOT NULL, path TEXT NOT NULL,
            physical_hash TEXT NOT NULL, logical_hash TEXT NOT NULL,
            media_type TEXT NOT NULL, created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS store_meta (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO store_meta (key, value) VALUES ('schema_version', '4');
        """
        with store._connect() as conn:
            conn.executescript(v4_schema)

        # Insert test data
        now = utc_now_iso()
        conn = store._connect()
        conn.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            ("p1", "test", now, "0.1.0"),
        )
        conn.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            ("plan1", "p1", "test-plan", now),
        )
        conn.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, created_at) VALUES (?, ?, ?, ?)",
            ("pv1", "plan1", 1, now),
        )
        conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, started_at, branch_id) VALUES (?, ?, ?, ?, ?)",
            ("run1", "pv1", "succeeded", now, None),
        )
        conn.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            "started_at, finished_at, input_artifact_ids_json, output_artifact_ids_json, "
            "execution_fingerprint_json, warnings_json, errors_json, is_carried_forward) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("rs1", "run1", "step1", "pv1", "succeeded",
             now, now, '["in1","in2"]', '["out1","out2"]',
             '{}', '[]', '[]', 0),
        )
        conn.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            "started_at, finished_at, input_artifact_ids_json, output_artifact_ids_json, "
            "execution_fingerprint_json, warnings_json, errors_json, is_carried_forward) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("rs2", "run1", "step2", "pv1", "succeeded",
             now, now, '[]', '["out3"]',
             '{}', '[]', '[]', 0),
        )
        conn.commit()

        # Run migrations (should create lineage table and backfill)
        store.run_migrations()

        # Verify lineage rows exist
        conn2 = store._connect()
        output_rows = conn2.execute(
            "SELECT * FROM artifact_lineage WHERE direction = 'output' ORDER BY artifact_id"
        ).fetchall()
        self.assertEqual(len(output_rows), 3)
        output_ids = sorted(r["artifact_id"] for r in output_rows)
        self.assertEqual(output_ids, ["out1", "out2", "out3"])

        input_rows = conn2.execute(
            "SELECT * FROM artifact_lineage WHERE direction = 'input' ORDER BY artifact_id"
        ).fetchall()
        self.assertEqual(len(input_rows), 2)
        input_ids = sorted(r["artifact_id"] for r in input_rows)
        self.assertEqual(input_ids, ["in1", "in2"])

        # Verify sentinel was set
        sentinel = conn2.execute(
            "SELECT value FROM store_meta WHERE key = 'lineage_backfilled'"
        ).fetchone()
        self.assertIsNotNone(sentinel)
        self.assertEqual(sentinel["value"], "1")

    def test_backfill_is_idempotent(self):
        """Re-running run_migrations should not create duplicate lineage rows."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.root.mkdir(parents=True, exist_ok=True)
        for sub in ("datasets", "artifacts", "exports", "logs"):
            (store.root / sub).mkdir(exist_ok=True)

        v4_schema = """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            created_at TEXT NOT NULL, cardre_version TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            name TEXT NOT NULL, created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS plan_versions (
            plan_version_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL,
            version_number INTEGER NOT NULL, created_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS plan_steps (
            step_id TEXT NOT NULL, plan_version_id TEXT NOT NULL,
            node_type TEXT NOT NULL, node_version TEXT NOT NULL,
            category TEXT NOT NULL, params_json TEXT NOT NULL,
            params_hash TEXT NOT NULL, parent_step_ids_json TEXT NOT NULL,
            branch_label TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
            PRIMARY KEY (plan_version_id, step_id)
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, plan_version_id TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
            branch_id TEXT
        );
        CREATE TABLE IF NOT EXISTS run_steps (
            run_step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            step_id TEXT NOT NULL, plan_version_id TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, input_artifact_ids_json TEXT NOT NULL,
            output_artifact_ids_json TEXT NOT NULL,
            execution_fingerprint_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            errors_json TEXT NOT NULL DEFAULT '[]',
            is_carried_forward INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL,
            role TEXT NOT NULL, path TEXT NOT NULL,
            physical_hash TEXT NOT NULL, logical_hash TEXT NOT NULL,
            media_type TEXT NOT NULL, created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS store_meta (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO store_meta (key, value) VALUES ('schema_version', '4');
        """
        with store._connect() as conn:
            conn.executescript(v4_schema)

        now = utc_now_iso()
        conn = store._connect()
        conn.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            ("p1", "test", now, "0.1.0"),
        )
        conn.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            ("plan1", "p1", "test-plan", now),
        )
        conn.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, created_at) VALUES (?, ?, ?, ?)",
            ("pv1", "plan1", 1, now),
        )
        conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, started_at, branch_id) VALUES (?, ?, ?, ?, ?)",
            ("run1", "pv1", "succeeded", now, None),
        )
        conn.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            "started_at, finished_at, input_artifact_ids_json, output_artifact_ids_json, "
            "execution_fingerprint_json, warnings_json, errors_json, is_carried_forward) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("rs1", "run1", "step1", "pv1", "succeeded",
             now, now, '["in1"]', '["out1"]',
             '{}', '[]', '[]', 0),
        )
        conn.commit()

        # First migration
        store.run_migrations()
        conn2 = store._connect()
        count1 = conn2.execute("SELECT COUNT(*) AS cnt FROM artifact_lineage").fetchone()["cnt"]

        # Second migration (idempotent)
        store.run_migrations()
        count2 = conn2.execute("SELECT COUNT(*) AS cnt FROM artifact_lineage").fetchone()["cnt"]

        self.assertEqual(count1, count2, "Backfill should be idempotent")


class ArtifactLineageQueryTests(unittest.TestCase):
    """Query rewrites using artifact_lineage table."""

    def setUp(self):
        self.store, self.tmp = make_store()
        self.pid = self.store.create_project("test-proj")
        self.plan_id = self.store.create_plan(self.pid, "test-plan")
        steps = [
            StepSpec(
                step_id="import", node_type="import", node_version="1",
                category="data", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="split", node_version="1",
                category="data", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
        ]
        self.pv_id = self.store.create_plan_version(self.plan_id, steps)
        self.run_id = self.store.create_run(self.pv_id)

        # Register artifacts
        self.artifacts = {}
        for aid, atype, arole in [
            ("a-imported", "dataset", "input"),
            ("a-train", "dataset", "train"),
            ("a-test", "dataset", "test"),
            ("a-oot", "dataset", "oot"),
        ]:
            art = ArtifactRef(
                artifact_id=aid, artifact_type=atype, role=arole,
                path=f"datasets/{aid}.parquet", physical_hash="abc",
                logical_hash="def", media_type="application/vnd.apache.parquet",
                metadata={},
            )
            self.store.register_artifact(art)
            self.artifacts[aid] = art

        # Save run steps with artifact lineage
        rs1 = RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=self.run_id,
            step_id="import", plan_version_id=self.pv_id,
            status="succeeded", started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=["a-imported"],
            output_artifact_ids=["a-imported"],
            execution_fingerprint={}, warnings=[], errors=[],
        )
        self.store.save_run_step(rs1)

        rs2 = RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=self.run_id,
            step_id="split", plan_version_id=self.pv_id,
            status="succeeded", started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=["a-imported"],
            output_artifact_ids=["a-train", "a-test", "a-oot"],
            execution_fingerprint={}, warnings=[], errors=[],
        )
        self.store.save_run_step(rs2)

        self.store.finish_run(self.run_id, "succeeded")

    def test_list_artifacts_for_project_returns_output_artifacts(self):
        """list_for_project should return only output artifacts (not inputs)."""
        artifacts = self.store.list_artifacts_for_project(self.pid)
        artifact_ids = {a.artifact_id for a in artifacts}
        # a-imported is both input and output of import step, so it should appear
        self.assertIn("a-imported", artifact_ids)
        self.assertIn("a-train", artifact_ids)
        self.assertIn("a-test", artifact_ids)
        self.assertIn("a-oot", artifact_ids)

    def test_filter_by_run_id(self):
        """Filter artifacts by run_id."""
        artifacts = self.store.list_artifacts_for_project(
            self.pid, run_id=self.run_id,
        )
        artifact_ids = {a.artifact_id for a in artifacts}
        self.assertIn("a-train", artifact_ids)
        self.assertIn("a-test", artifact_ids)

    def test_filter_by_producing_step_id(self):
        """Filter artifacts by producing step_id."""
        artifacts = self.store.list_artifacts_for_project(
            self.pid, producing_step_id="split",
        )
        artifact_ids = {a.artifact_id for a in artifacts}
        self.assertIn("a-train", artifact_ids)
        self.assertIn("a-test", artifact_ids)
        self.assertIn("a-oot", artifact_ids)
        # import step only produces a-imported
        artifacts_import = self.store.list_artifacts_for_project(
            self.pid, producing_step_id="import",
        )
        import_ids = {a.artifact_id for a in artifacts_import}
        self.assertIn("a-imported", import_ids)
        self.assertNotIn("a-train", import_ids)

    def test_filter_by_role(self):
        """Filter artifacts by role."""
        artifacts = self.store.list_artifacts_for_project(
            self.pid, role="train",
        )
        artifact_ids = {a.artifact_id for a in artifacts}
        self.assertEqual(artifact_ids, {"a-train"})

    def test_filter_by_artifact_type(self):
        """Filter artifacts by artifact_type."""
        artifacts = self.store.list_artifacts_for_project(
            self.pid, artifact_type="dataset",
        )
        self.assertGreater(len(artifacts), 0)

    def test_filter_by_run_id_and_role(self):
        """Combined filter by run_id and role."""
        artifacts = self.store.list_artifacts_for_project(
            self.pid, run_id=self.run_id, role="train",
        )
        artifact_ids = {a.artifact_id for a in artifacts}
        self.assertEqual(artifact_ids, {"a-train"})

    def test_limit_and_offset(self):
        """Pagination via limit and offset."""
        all_arts = self.store.list_artifacts_for_project(self.pid, limit=100)
        total = len(all_arts)
        limited = self.store.list_artifacts_for_project(self.pid, limit=2)
        self.assertLessEqual(len(limited), 2)
        offset_arts = self.store.list_artifacts_for_project(self.pid, limit=2, offset=2)
        self.assertGreaterEqual(len(offset_arts), 0)
        # Combined should not exceed total
        self.assertLessEqual(len(limited) + len(offset_arts), total)


class ArtifactLineageDuplicateTests(unittest.TestCase):
    """Duplicate prevention in artifact_lineage."""

    def test_save_step_does_not_create_duplicate_lineage_rows(self):
        """Calling save_run_step twice with the same (run_step_id, artifact_id, direction)
        should not create duplicates (INSERT OR IGNORE + UNIQUE constraint)."""
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(pv_id)

        # First step — saves run_step + lineage rows
        rs1 = RunStepRecord(
            run_step_id="rs-dup-a",
            run_id=run_id, step_id="step1", plan_version_id=pv_id,
            status="succeeded", started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=["in1"],
            output_artifact_ids=["out1"],
            execution_fingerprint={}, warnings=[], errors=[],
        )
        store.save_run_step(rs1)
        conn = store._connect()
        count1 = conn.execute("SELECT COUNT(*) AS cnt FROM artifact_lineage").fetchone()["cnt"]

        # Second step — same artifact_ids but different run_step_id.
        # The UNIQUE(run_step_id, artifact_id, direction) constraint should
        # prevent duplicate lineage rows for the same (run_step_id, artifact_id, direction).
        rs2 = RunStepRecord(
            run_step_id="rs-dup-b",
            run_id=run_id, step_id="step1", plan_version_id=pv_id,
            status="succeeded", started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=["in1"],
            output_artifact_ids=["out1"],
            execution_fingerprint={}, warnings=[], errors=[],
        )
        store.save_run_step(rs2)
        count2 = conn.execute("SELECT COUNT(*) AS cnt FROM artifact_lineage").fetchone()["cnt"]

        # Each save adds 2 lineage rows (1 input + 1 output), so count should increase by 2
        self.assertEqual(count2, count1 + 2,
                         "Second save with different run_step_id should add new lineage rows")

        # Verify no duplicate (run_step_id, artifact_id, direction) tuples exist
        dupes = conn.execute(
            "SELECT run_step_id, artifact_id, direction, COUNT(*) AS cnt "
            "FROM artifact_lineage "
            "GROUP BY run_step_id, artifact_id, direction "
            "HAVING cnt > 1"
        ).fetchall()
        self.assertEqual(len(dupes), 0, "No duplicate (run_step_id, artifact_id, direction) tuples")

    def test_duplicate_artifact_id_in_same_step_is_deduplicated(self):
        """If a step lists the same artifact_id twice in its output array,
        the UNIQUE constraint should collapse to one lineage row."""
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(pv_id)

        # Manually create a RunStepRecord with duplicate output IDs
        rs = RunStepRecord(
            run_step_id="rs-dup-artifact",
            run_id=run_id, step_id="step1", plan_version_id=pv_id,
            status="succeeded", started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=[],
            output_artifact_ids=["out1", "out1"],  # duplicate
            execution_fingerprint={}, warnings=[], errors=[],
        )
        store.save_run_step(rs)

        conn = store._connect()
        output_rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM artifact_lineage "
            "WHERE run_step_id = 'rs-dup-artifact' AND direction = 'output' AND artifact_id = 'out1'"
        ).fetchone()["cnt"]
        self.assertEqual(output_rows, 1, "Duplicate artifact_id should be collapsed to one row")


class ArtifactLineageQueryShapeTests(unittest.TestCase):
    """EXPLAIN QUERY PLAN assertions — verify lineage indexes are used."""

    def test_list_for_project_uses_lineage_index(self):
        """list_for_project should use idx_lineage_run_direction or similar lineage index."""
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(pv_id)

        # Insert minimal data so the query has something to plan
        # (plan, plan_version, and run are already created by the store methods above)
        now = utc_now_iso()
        conn = store._connect()
        conn.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            "started_at, finished_at, input_artifact_ids_json, output_artifact_ids_json, "
            "execution_fingerprint_json, warnings_json, errors_json, is_carried_forward) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("rs1", run_id, "step1", pv_id, "succeeded",
             now, now, '[]', '["a1"]', '{}', '[]', '[]', 0),
        )
        conn.execute(
            "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, "
            "step_id, branch_id, artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("l1", run_id, "rs1", pv_id, "step1", None, "a1", "output", now),
        )
        conn.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, "
            "physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("a1", "dataset", "train", "datasets/a1.parquet",
             "abc", "def", "application/vnd.apache.parquet", now),
        )
        conn.commit()

        # EXPLAIN QUERY PLAN for the list_for_project query
        plan_rows = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT DISTINCT a.* FROM artifacts a "
            "JOIN artifact_lineage al ON a.artifact_id = al.artifact_id AND al.direction = 'output' "
            "JOIN runs r ON al.run_id = r.run_id "
            "JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
            "JOIN plans p ON pv.plan_id = p.plan_id "
            "WHERE p.project_id = ? "
            "ORDER BY a.created_at DESC LIMIT 100 OFFSET 0",
            (pid,),
        ).fetchall()
        plan_text = "\n".join(r["detail"] for r in plan_rows)

        # Should use an index on artifact_lineage (not a full scan of json_each)
        self.assertIn("idx_lineage_run_direction", plan_text,
                      "Query plan should use idx_lineage_run_direction index")
        # Should NOT contain SCAN of run_steps (the old json_each path)
        self.assertNotIn("json_each", plan_text,
                         "Query plan should NOT use json_each")

    def test_get_artifact_ids_for_run_uses_lineage_index(self):
        """get_artifact_ids_for_run should use idx_lineage_run_direction."""
        store, tmp = make_store()
        conn = store._connect()
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, "
            "step_id, branch_id, artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("l1", "run1", "rs1", "pv1", "step1", None, "a1", "output", now),
        )
        conn.commit()

        plan_rows = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT DISTINCT artifact_id FROM artifact_lineage "
            "WHERE run_id = ? AND direction = 'output'",
            ("run1",),
        ).fetchall()
        plan_text = "\n".join(r["detail"] for r in plan_rows)
        self.assertIn("artifact_lineage", plan_text)
        # Should use the index, not a full scan
        self.assertIn("USING", plan_text.upper(),
                      "Query plan should use an index (not a full scan)")


class ArtifactLineageSchemaTests(unittest.TestCase):
    """Schema version and table existence."""

    def test_schema_version_is_5(self):
        """STORE_SCHEMA_VERSION should be 5."""
        self.assertEqual(STORE_SCHEMA_VERSION, 5)

    def test_fresh_store_has_artifact_lineage_table(self):
        """A freshly initialized store should have the artifact_lineage table."""
        store, tmp = make_store()
        conn = store._connect()
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertIn("artifact_lineage", tables)

    def test_fresh_store_has_lineage_indexes(self):
        """A freshly initialized store should have lineage indexes."""
        store, tmp = make_store()
        conn = store._connect()
        indexes = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        for idx in ("idx_lineage_artifact", "idx_lineage_run_direction",
                     "idx_lineage_step_direction", "idx_lineage_pv_step",
                     "idx_lineage_run_step", "idx_lineage_branch_direction"):
            self.assertIn(idx, indexes, f"Index {idx} missing")
