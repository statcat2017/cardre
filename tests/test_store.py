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
            "runs", "run_steps", "artifacts",
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


# ======================================================================
# Slice 4: Concurrent run prevention
# ======================================================================

class ConcurrentRunTests(unittest.TestCase):

    def _setup_run(self, store):
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        return pid, plan_id, pv_id

    def test_create_run_raises_when_run_in_progress(self) -> None:
        store, tmp = make_store()
        _, _, pv_id = self._setup_run(store)
        r1 = store.create_run(pv_id)
        self.assertIsNotNone(r1)
        from cardre.errors import ConcurrentRunError
        with self.assertRaises(ConcurrentRunError):
            store.create_run(pv_id)

    def test_create_run_force_bypasses_check(self) -> None:
        store, tmp = make_store()
        _, _, pv_id = self._setup_run(store)
        r1 = store.create_run(pv_id)
        self.assertIsNotNone(r1)
        r2 = store.create_run(pv_id, force=True)
        self.assertIsNotNone(r2)
        self.assertNotEqual(r1, r2)

    def test_finished_run_does_not_block(self) -> None:
        store, tmp = make_store()
        _, _, pv_id = self._setup_run(store)
        r1 = store.create_run(pv_id)
        store.finish_run(r1, "succeeded")
        r2 = store.create_run(pv_id)
        self.assertIsNotNone(r2)

    def test_concurrent_check_scoped_by_plan_version(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv1_id = store.create_plan_version(plan_id, [])
        pv2_id = store.create_plan_version(plan_id, [])
        r1 = store.create_run(pv1_id)
        self.assertIsNotNone(r1)
        r2 = store.create_run(pv2_id)
        self.assertIsNotNone(r2)

    def test_concurrent_check_scoped_by_branch(self) -> None:
        store, tmp = make_store()
        _, _, pv_id = self._setup_run(store)
        r_main = store.create_run(pv_id, branch_id=None)
        self.assertIsNotNone(r_main)
        r_branch = store.create_run(pv_id, branch_id="branch-1")
        self.assertIsNotNone(r_branch)
        r_branch2 = store.create_run(pv_id, branch_id="branch-2")
        self.assertIsNotNone(r_branch2)
        from cardre.errors import ConcurrentRunError
        with self.assertRaises(ConcurrentRunError):
            store.create_run(pv_id, branch_id="branch-1")


# ======================================================================
# Slice 5: Stale run recovery
# ======================================================================

class StaleRunRecoveryTests(unittest.TestCase):

    def _setup_recovery_run(self, store):
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        return store.create_run(pv_id)

    def test_recover_marks_old_running_as_interrupted(self) -> None:
        store, tmp = make_store()
        run_id = self._setup_recovery_run(store)
        # Manually backdate the started_at AND heartbeat_at to be old
        old_time = "2020-01-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET started_at = ?, heartbeat_at = ? WHERE run_id = ?",
            (old_time, old_time, run_id),
        )
        recovered = store.recover_interrupted_runs(max_age_seconds=1)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["run_id"], run_id)
        # Verify status changed
        run = store.get_run(run_id)
        self.assertEqual(run["status"], "interrupted")

    def test_recent_running_unaffected(self) -> None:
        store, tmp = make_store()
        run_id = self._setup_recovery_run(store)
        recovered = store.recover_interrupted_runs(max_age_seconds=86400)
        self.assertEqual(len(recovered), 0)
        run = store.get_run(run_id)
        self.assertEqual(run["status"], "running")

    def test_recover_runs_explicit_call(self) -> None:
        import tempfile
        from pathlib import Path
        from cardre.store import ProjectStore

        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.initialize()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(pv_id)
        old_time = "2021-06-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET started_at = ?, heartbeat_at = ? WHERE run_id = ?",
            (old_time, old_time, run_id),
        )
        store._connect().commit()
        store2 = ProjectStore(tmp / "test.cardre")
        store2._connect()
        recovered = store2.recover_interrupted_runs()
        self.assertGreaterEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["run_id"], run_id)
        run = store2.get_run(run_id)
        self.assertEqual(run["status"], "interrupted")


# ======================================================================
# Slice 6: Heartbeat and recovery safety
# ======================================================================

class HeartbeatTests(unittest.TestCase):

    def _setup_run(self, store):
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        return store.create_run(pv_id)

    def test_heartbeat_updates_timestamp(self) -> None:
        store, tmp = make_store()
        run_id = self._setup_run(store)
        # Manually set heartbeat to a known old value
        old_time = "2020-01-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?",
            (old_time, run_id),
        )
        store.run_heartbeat(run_id)
        run = store.get_run(run_id)
        self.assertGreater(run["heartbeat_at"], old_time)

    def test_active_heartbeat_prevents_recovery(self) -> None:
        store, tmp = make_store()
        run_id = self._setup_run(store)
        # Backdate started_at but keep a recent heartbeat
        old_time = "2020-01-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET started_at = ? WHERE run_id = ?",
            (old_time, run_id),
        )
        store.run_heartbeat(run_id)  # now heartbeat_at is recent
        recovered = store.recover_interrupted_runs(max_age_seconds=1)
        self.assertEqual(len(recovered), 0)
        run = store.get_run(run_id)
        self.assertEqual(run["status"], "running")

    def test_old_heartbeat_allows_recovery(self) -> None:
        store, tmp = make_store()
        run_id = self._setup_run(store)
        old_time = "2020-01-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET started_at = ?, heartbeat_at = ? WHERE run_id = ?",
            (old_time, old_time, run_id),
        )
        recovered = store.recover_interrupted_runs(max_age_seconds=1)
        self.assertEqual(len(recovered), 1)
        run = store.get_run(run_id)
        self.assertEqual(run["status"], "interrupted")


# ======================================================================
# Slice 7: Concurrent-connection race test for BEGIN IMMEDIATE
# ======================================================================

class ConcurrentConnectionTests(unittest.TestCase):
    """Verify that two ProjectStore instances on the same path serialise
    create_run correctly via BEGIN IMMEDIATE."""

    def test_two_connections_serialise_create_run(self) -> None:
        import tempfile
        from pathlib import Path
        from cardre.store import ProjectStore

        tmp = Path(tempfile.mkdtemp())
        s1 = ProjectStore(tmp / "test.cardre")
        s1.initialize()
        pid = s1.create_project("test")
        plan_id = s1.create_plan(pid, "test-plan")
        pv_id = s1.create_plan_version(plan_id, [])

        s2 = ProjectStore(tmp / "test.cardre")
        s2._connect()  # open the same SQLite file

        results: list[str] = []
        errors: list[str] = []

        def try_create(store, label):
            from cardre.errors import ConcurrentRunError
            try:
                rid = store.create_run(pv_id)
                results.append(f"{label}:{rid}")
            except ConcurrentRunError:
                errors.append(f"{label}:rejected")

        import threading
        t1 = threading.Thread(target=try_create, args=(s1, "s1"))
        t2 = threading.Thread(target=try_create, args=(s2, "s2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one should succeed, the other should be rejected
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)

    def test_two_connections_force_bypasses(self) -> None:
        import tempfile
        from pathlib import Path
        from cardre.store import ProjectStore

        tmp = Path(tempfile.mkdtemp())
        s1 = ProjectStore(tmp / "test.cardre")
        s1.initialize()
        pid = s1.create_project("test")
        plan_id = s1.create_plan(pid, "test-plan")
        pv_id = s1.create_plan_version(plan_id, [])

        s2 = ProjectStore(tmp / "test.cardre")
        s2._connect()

        results: list[str] = []
        errors: list[str] = []

        def try_force(store, label):
            from cardre.errors import ConcurrentRunError
            try:
                rid = store.create_run(pv_id, force=True)
                results.append(f"{label}:{rid}")
            except ConcurrentRunError:
                errors.append(f"{label}:rejected")

        import threading
        t1 = threading.Thread(target=try_force, args=(s1, "s1"))
        t2 = threading.Thread(target=try_force, args=(s2, "s2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both should succeed (force bypasses check)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(errors), 0)
        # Both should be distinct run IDs
        self.assertNotEqual(results[0].split(":")[1], results[1].split(":")[1])


# ======================================================================
# Slice 8: Schema version guard
# ======================================================================

class SchemaVersionGuardTests(unittest.TestCase):

    def test_new_store_gets_schema_version_stamped(self) -> None:
        store, tmp = make_store()
        row = store._connect().execute(
            "SELECT value FROM store_meta WHERE key = 'schema_version'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row["value"]), 3)

    def test_schema_version_accepts_compatible(self) -> None:
        store, tmp = make_store()
        store._check_schema_version()  # should not raise

    def test_schema_version_rejects_newer(self) -> None:
        store, tmp = make_store()
        store._connect().execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_version', '99')"
        )
        from cardre.errors import SchemaVersionError
        with self.assertRaises(SchemaVersionError):
            store._check_schema_version()


# ======================================================================
# Slice 9: Integrity report
# ======================================================================

class IntegrityTests(unittest.TestCase):

    def test_clean_store_has_empty_report(self) -> None:
        store, tmp = make_store()
        report = store.verify_integrity()
        self.assertEqual(len(report.missing_artifact_files), 0)
        self.assertEqual(len(report.orphan_artifact_files), 0)
        self.assertEqual(len(report.dangling_run_step_refs), 0)
        self.assertEqual(len(report.stale_running_runs), 0)

    def test_missing_artifact_file_is_reported(self) -> None:
        store, tmp = make_store()
        artifact = _register_dummy_artifact(store)
        # Delete the file behind the store's back
        p = store.artifact_path(artifact)
        if p.exists():
            p.unlink()
        report = store.verify_integrity()
        self.assertEqual(len(report.missing_artifact_files), 1)
        self.assertEqual(report.missing_artifact_files[0]["artifact_id"], artifact.artifact_id)

    def test_orphan_file_is_reported(self) -> None:
        store, tmp = make_store()
        # Drop an unregistered file into the datasets directory
        orphan_path = store.root / "datasets" / "orphan_test.parquet"
        orphan_path.write_bytes(b"fake parquet data")
        report = store.verify_integrity()
        self.assertGreaterEqual(len(report.orphan_artifact_files), 1)
        self.assertTrue(
            any("orphan_test.parquet" in o["path"] for o in report.orphan_artifact_files)
        )

    def test_dangling_run_step_ref_is_reported(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(pv_id)
        from cardre.audit import RunStepRecord, utc_now_iso
        rs = RunStepRecord(
            run_step_id="dangling-rs",
            run_id=run_id,
            step_id="import",
            plan_version_id=pv_id,
            status="succeeded",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=[],
            output_artifact_ids=["nonexistent-artifact-id"],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        )
        store.save_run_step(rs)
        report = store.verify_integrity()
        self.assertGreaterEqual(len(report.dangling_run_step_refs), 1)
        self.assertEqual(report.dangling_run_step_refs[0]["artifact_id"], "nonexistent-artifact-id")

    def test_stale_running_run_is_reported(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(pv_id)
        # Backdate both timestamps
        old = "2020-01-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET started_at = ?, heartbeat_at = ? WHERE run_id = ?",
            (old, old, run_id),
        )
        report = store.verify_integrity(stale_run_max_age_seconds=1)
        self.assertGreaterEqual(len(report.stale_running_runs), 1)
        self.assertEqual(report.stale_running_runs[0]["run_id"], run_id)

    def test_dangling_input_ref_is_reported(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(pv_id)
        from cardre.audit import RunStepRecord, utc_now_iso
        rs = RunStepRecord(
            run_step_id="dangling-input-rs",
            run_id=run_id,
            step_id="import",
            plan_version_id=pv_id,
            status="succeeded",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=["nonexistent-input-id"],
            output_artifact_ids=[],
            execution_fingerprint={},
            warnings=[],
            errors=[],
        )
        store.save_run_step(rs)
        report = store.verify_integrity()
        matching = [r for r in report.dangling_run_step_refs if r["artifact_id"] == "nonexistent-input-id"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["direction"], "input")


def _register_dummy_artifact(store: ProjectStore) -> ArtifactRef:
    """Create and register a small artifact, returning the ref."""
    import uuid
    from cardre.audit import ArtifactRef, physical_hash
    from cardre.store import ProjectStore
    ref = store.ingest_existing_artifact(
        source_path=Path(__file__),  # any small file
        artifact_type="test",
        role="input",
        media_type="text/plain",
    )
    return ref


# ======================================================================
# Slice 10: Export atomicity
# ======================================================================

class ExportAtomicityTests(unittest.TestCase):

    def test_export_writes_to_temp_then_final(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        from cardre.services.export_service import export_branch_audit_pack
        result = export_branch_audit_pack(
            store=store, project_id=pid, plan_id=plan_id,
            branch_id=branch_id,
        )
        export_path = Path(result["export_path"])
        self.assertTrue(export_path.exists())
        self.assertTrue((export_path / "project.json").exists())
        self.assertTrue((export_path / "branch.json").exists())
        # Verify no temp dir was left behind
        parent = export_path.parent
        tmp_leftovers = list(parent.glob(f".{export_path.name}.tmp.*"))
        self.assertEqual(len(tmp_leftovers), 0)

    def test_export_failure_cleans_up_temp_dir(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        # Patch _write_json to always raise
        import cardre.services.export_service as svc
        original = svc._write_json

        def _failing_write(path, data):
            raise IOError("simulated export failure")

        svc._write_json = _failing_write
        try:
            with self.assertRaises(IOError):
                from cardre.services.export_service import export_branch_audit_pack
                export_branch_audit_pack(
                    store=store, project_id=pid, plan_id=plan_id,
                    branch_id=branch_id,
                )
        finally:
            svc._write_json = original

        # Verify no export dir exists
        export_dir = store.root / "exports"
        self.assertTrue(export_dir.exists())
        # Any audit dirs should be real exports only (no temp dirs left)
        for d in export_dir.iterdir():
            self.assertFalse(d.name.startswith("."), f"Temp dir left behind: {d}")
            self.assertFalse(d.name.endswith(".tmp"), f"Temp dir left behind: {d}")

    def test_export_overwrite_preserves_old_on_failure(self) -> None:
        store, tmp = make_store()
        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [])
        branch_id = store.create_branch(
            project_id=pid, plan_id=plan_id,
            name="Baseline", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        from cardre.services.export_service import export_branch_audit_pack
        # First export succeeds
        result1 = export_branch_audit_pack(
            store=store, project_id=pid, plan_id=plan_id,
            branch_id=branch_id,
        )
        export_path = Path(result1["export_path"])
        self.assertTrue(export_path.exists())

        # Second export with the same path fails because _write_json is patched
        import cardre.services.export_service as svc
        original = svc._write_json
        def _failing_write(path, data):
            raise IOError("simulated export failure")
        svc._write_json = _failing_write
        try:
            with self.assertRaises(IOError):
                export_branch_audit_pack(
                    store=store, project_id=pid, plan_id=plan_id,
                    branch_id=branch_id, export_path=str(export_path),
                )
        finally:
            svc._write_json = original

        # The first export should still be intact
        self.assertTrue(export_path.exists())
        self.assertTrue((export_path / "project.json").exists())
        # Verify no backup dirs were left behind
        for d in export_path.parent.iterdir():
            self.assertFalse(d.name.startswith(".") and "backup" in d.name,
                            f"Backup dir left behind: {d}")
