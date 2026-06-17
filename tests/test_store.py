"""Tests for cardre.store — ProjectStore, schema, and branch CRUD."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cardre.audit import (
    ArtifactRef,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
    utc_now_iso,
)
from cardre.store import ProjectStore

from tests.helpers import make_store


# ======================================================================
# Slice 1: SQLite Schema + ProjectStore
# ======================================================================

class ProjectStoreTests(unittest.TestCase):

    def test_creating_project_creates_directories_and_sqlite(self) -> None:
        store, tmp = make_store()
        self.assertTrue((tmp / "test.cardre").exists())
        self.assertTrue((tmp / "test.cardre" / "cardre.sqlite").exists())
        for sub in ("datasets", "artifacts", "exports", "logs"):
            self.assertTrue((tmp / "test.cardre" / sub).is_dir())

    def test_schema_exists_after_initialization(self) -> None:
        store, tmp = make_store()
        tables = [
            "projects", "plans", "plan_versions", "plan_steps",
            "runs", "run_steps", "artifacts", "warnings", "errors",
        ]
        conn = store._connect()
        existing = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for t in tables:
            self.assertIn(t, existing, f"Table {t} missing from schema")

    def test_sqlite_contains_no_tabular_blobs(self) -> None:
        store, tmp = make_store()
        # Insert a small row in each table
        now = utc_now_iso()
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
                ("p1", "test", now, "0.1.0"),
            )
            conn.execute(
                "INSERT INTO artifacts (artifact_id, artifact_type, role, path, "
                "physical_hash, logical_hash, media_type, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("a1", "dataset", "input", "datasets/test.parquet",
                 "abc", "def", "application/vnd.apache.parquet", now),
            )
        # No row should exceed 100KB for these small tables
        self.assertTrue(store.verify_no_tabular_blobs())

    def test_register_artifact_writes_metadata_and_preserves_path(self) -> None:
        store, tmp = make_store()
        artifact = ArtifactRef(
            artifact_id="art-001",
            artifact_type="dataset",
            role="input",
            path="datasets/test.parquet",
            physical_hash="abc123",
            logical_hash="def456",
            media_type="application/vnd.apache.parquet",
            metadata={"source": "test"},
        )
        store.register_artifact(artifact)
        retrieved = store.get_artifact("art-001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.path, "datasets/test.parquet")
        self.assertEqual(retrieved.physical_hash, "abc123")

    def test_project_create_and_get(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("my-project")
        proj = store.get_project(pid)
        self.assertIsNotNone(proj)
        self.assertEqual(proj["name"], "my-project")


# ======================================================================
# Slice 2: Schema migration
# ======================================================================

class SchemaMigrationTests(unittest.TestCase):

    def test_fresh_store_has_branch_tables(self) -> None:
        store, tmp = make_store()
        conn = store._connect()
        existing = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected_tables = {
            "plan_branches", "branch_step_map", "branch_comparisons",
            "branch_comparison_snapshots", "champion_assignments",
        }
        for t in expected_tables:
            self.assertIn(t, existing, f"Table {t} missing from schema")

    def test_fresh_store_has_canonical_step_id_column(self) -> None:
        store, tmp = make_store()
        conn = store._connect()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(plan_steps)").fetchall()}
        self.assertIn("canonical_step_id", cols)
        self.assertIn("branch_id", cols)

    def test_legacy_store_gets_columns_after_migration(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.root.mkdir(parents=True, exist_ok=True)
        for sub in ("datasets", "artifacts", "exports", "logs"):
            (store.root / sub).mkdir(exist_ok=True)

        # Create old schema without branch columns
        old_schema = """
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
            finished_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS run_steps (
            run_step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            step_id TEXT NOT NULL, plan_version_id TEXT NOT NULL,
            status TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, input_artifact_ids_json TEXT NOT NULL,
            output_artifact_ids_json TEXT NOT NULL,
            execution_fingerprint_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL DEFAULT '[]',
            errors_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL,
            role TEXT NOT NULL, path TEXT NOT NULL,
            physical_hash TEXT NOT NULL, logical_hash TEXT NOT NULL,
            media_type TEXT NOT NULL, created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        """
        with store._connect() as conn:
            conn.executescript(old_schema)

        # Verify old columns only
        cols_before = {r["name"] for r in store._connect().execute("PRAGMA table_info(plan_steps)").fetchall()}
        self.assertNotIn("canonical_step_id", cols_before)
        self.assertNotIn("branch_id", cols_before)

        # Run migration
        store.run_migrations()

        # Verify new columns exist
        cols_after = {r["name"] for r in store._connect().execute("PRAGMA table_info(plan_steps)").fetchall()}
        self.assertIn("canonical_step_id", cols_after)
        self.assertIn("branch_id", cols_after)

        # Verify branch tables exist
        existing = {
            r["name"]
            for r in store._connect().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected_tables = {
            "plan_branches", "branch_step_map", "branch_comparisons",
            "branch_comparison_snapshots", "champion_assignments",
        }
        for t in expected_tables:
            self.assertIn(t, existing, f"Table {t} missing from migrated store")

    def test_migration_idempotent(self) -> None:
        store, tmp = make_store()
        store.run_migrations()
        store.run_migrations()
        conn = store._connect()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(plan_steps)").fetchall()}
        self.assertIn("canonical_step_id", cols)
        self.assertIn("branch_id", cols)


# ======================================================================
# Slice 3: Branch CRUD methods on ProjectStore
# ======================================================================

class BranchCrudTests(unittest.TestCase):

    def setUp(self) -> None:
        self.store, self.tmp = make_store()
        self.project_id = self.store.create_project("test-proj")
        self.plan_id = self.store.create_plan(self.project_id, "Scorecard Pathway")
        self.pv_id = self.store.create_plan_version(self.plan_id, [], description="v1")

    def test_create_and_get_branch(self) -> None:
        branch_id = self.store.create_branch(
            project_id=self.project_id,
            plan_id=self.plan_id,
            name="Baseline",
            branch_type="baseline",
            base_plan_version_id=self.pv_id,
            head_plan_version_id=self.pv_id,
            created_reason="Test baseline branch.",
        )
        branch = self.store.get_branch(branch_id)
        self.assertIsNotNone(branch)
        self.assertEqual(branch["name"], "Baseline")
        self.assertEqual(branch["branch_type"], "baseline")
        self.assertEqual(branch["status"], "active")

    def test_list_branches(self) -> None:
        b1 = self.store.create_branch(
            project_id=self.project_id, plan_id=self.plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=self.pv_id, head_plan_version_id=self.pv_id,
            created_reason="Initial branch.",
        )
        branches = self.store.list_branches(self.project_id)
        self.assertGreaterEqual(len(branches), 1)
        self.assertTrue(any(b["branch_id"] == b1 for b in branches))

    def test_list_branches_filters_by_plan(self) -> None:
        plan2_id = self.store.create_plan(self.project_id, "Other Plan")
        pv2_id = self.store.create_plan_version(plan2_id, [])
        b1 = self.store.create_branch(
            project_id=self.project_id, plan_id=self.plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=self.pv_id, head_plan_version_id=self.pv_id,
            created_reason="Initial branch.",
        )
        b2 = self.store.create_branch(
            project_id=self.project_id, plan_id=plan2_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=pv2_id, head_plan_version_id=pv2_id,
            created_reason="Other branch.",
        )
        plan1_branches = self.store.list_branches(self.project_id, plan_id=self.plan_id)
        self.assertTrue(any(b["branch_id"] == b1 for b in plan1_branches))
        self.assertFalse(any(b["branch_id"] == b2 for b in plan1_branches))

    def test_list_branches_filters_by_type(self) -> None:
        b1 = self.store.create_branch(
            project_id=self.project_id, plan_id=self.plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=self.pv_id, head_plan_version_id=self.pv_id,
            created_reason="Initial branch.",
        )
        baseline_branches = self.store.list_branches(self.project_id, branch_type="baseline")
        self.assertTrue(any(b["branch_id"] == b1 for b in baseline_branches))
        model_branches = self.store.list_branches(self.project_id, branch_type="model_challenger")
        self.assertFalse(any(b["branch_id"] == b1 for b in model_branches))

    def test_update_branch_head(self) -> None:
        branch_id = self.store.create_branch(
            project_id=self.project_id, plan_id=self.plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=self.pv_id, head_plan_version_id=self.pv_id,
            created_reason="Initial branch.",
        )
        new_pv_id = self.store.create_plan_version(self.plan_id, [], description="v2")
        self.store.update_branch_head(branch_id, new_pv_id)
        branch = self.store.get_branch(branch_id)
        self.assertEqual(branch["head_plan_version_id"], new_pv_id)

    def test_create_and_get_branch_step_map(self) -> None:
        branch_id = self.store.create_branch(
            project_id=self.project_id, plan_id=self.plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=self.pv_id, head_plan_version_id=self.pv_id,
            created_reason="Initial branch.",
        )
        map_id = self.store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=self.pv_id,
            canonical_step_id="import", step_id="import",
            is_shared_upstream=False, is_branch_owned=True,
        )
        rows = self.store.get_branch_step_map(branch_id, self.pv_id)
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(any(r["branch_step_map_id"] == map_id for r in rows))

    def test_get_branch_step_map_all_versions(self) -> None:
        branch_id = self.store.create_branch(
            project_id=self.project_id, plan_id=self.plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=self.pv_id, head_plan_version_id=self.pv_id,
            created_reason="Initial branch.",
        )
        self.store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=self.pv_id,
            canonical_step_id="import", step_id="import",
        )
        rows = self.store.get_branch_step_map(branch_id)
        self.assertGreaterEqual(len(rows), 1)
