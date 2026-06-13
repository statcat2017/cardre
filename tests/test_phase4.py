"""Phase 4 Batch 0 acceptance tests.

Tests cover:
- StepSpec backwards-compatible extension
- Branch table schema migration
- ProjectStore branch CRUD methods
- Baseline branch migration service
- Pre-Phase-4 legacy fixture migration
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cardre.audit import StepSpec, json_logical_hash, replace_step_params
from cardre.store import ProjectStore
from cardre.services import migrate_project_to_branch_model
from cardre.services.migration_service import migrate_project_to_branch_model as _migrate
from sidecar.proof_pathway import (
    PROOF_PATHWAY_STEPS_CONFIG,
    PHASE2A_PATHWAY_STEPS_CONFIG,
    _build_steps,
)

from tests.test_phase1 import make_store, SAMPLE_GERMAN_CREDIT_LINES


# ======================================================================
# Slice 1: StepSpec backwards-compatible branch fields
# ======================================================================

class StepSpecBranchExtensionTests(unittest.TestCase):

    def test_legacy_construction_backfills_canonical_step_id(self) -> None:
        spec = StepSpec(
            step_id="manual-binning",
            node_type="cardre.manual_binning",
            node_version="1",
            category="refinement",
            params={},
            params_hash="abc",
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertIsNone(spec.branch_id)

    def test_branch_step_preserves_canonical_step_id(self) -> None:
        spec = StepSpec(
            step_id="manual-binning__br_a81f3c",
            node_type="cardre.manual_binning",
            node_version="1",
            category="refinement",
            params={},
            params_hash="abc",
            parent_step_ids=[],
            branch_label="Coarser bins",
            position=0,
            canonical_step_id="manual-binning",
            branch_id="br_a81f3c",
        )
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertEqual(spec.branch_id, "br_a81f3c")

    def test_to_dict_includes_branch_fields(self) -> None:
        spec = StepSpec(
            step_id="manual-binning__br_a81f3c",
            node_type="cardre.manual_binning",
            node_version="1",
            category="refinement",
            params={},
            params_hash="abc",
            parent_step_ids=[],
            branch_label="",
            position=0,
            canonical_step_id="manual-binning",
            branch_id="br_a81f3c",
        )
        d = spec.to_dict()
        self.assertEqual(d["canonical_step_id"], "manual-binning")
        self.assertEqual(d["branch_id"], "br_a81f3c")

    def test_from_dict_tolerates_legacy_missing_fields(self) -> None:
        data = {
            "step_id": "manual-binning",
            "node_type": "cardre.manual_binning",
            "node_version": "1",
            "category": "refinement",
            "params": {},
            "params_hash": "abc",
            "parent_step_ids": [],
            "branch_label": "",
            "position": 0,
        }
        spec = StepSpec.from_dict(data)
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertIsNone(spec.branch_id)

    def test_from_dict_reads_branch_fields_when_present(self) -> None:
        data = {
            "step_id": "manual-binning__br_a81f3c",
            "node_type": "cardre.manual_binning",
            "node_version": "1",
            "category": "refinement",
            "params": {},
            "params_hash": "abc",
            "parent_step_ids": [],
            "branch_label": "",
            "position": 0,
            "canonical_step_id": "manual-binning",
            "branch_id": "br_a81f3c",
        }
        spec = StepSpec.from_dict(data)
        self.assertEqual(spec.canonical_step_id, "manual-binning")
        self.assertEqual(spec.branch_id, "br_a81f3c")

    def test_replace_step_params_preserves_branch_fields(self) -> None:
        steps = [
            StepSpec(
                step_id="manual-binning__br_a81f3c",
                node_type="cardre.manual_binning",
                node_version="1",
                category="refinement",
                params={"overrides": []},
                params_hash=json_logical_hash({"overrides": []}),
                parent_step_ids=["fine-classing", "variable-selection"],
                branch_label="Coarser bins",
                position=5,
                canonical_step_id="manual-binning",
                branch_id="br_a81f3c",
            ),
        ]
        new_steps = replace_step_params(steps, "manual-binning__br_a81f3c", {"overrides": [{"variable": "x", "merge": [1, 2]}]})
        self.assertEqual(new_steps[0].canonical_step_id, "manual-binning")
        self.assertEqual(new_steps[0].branch_id, "br_a81f3c")

    def test_replace_step_params_preserves_branch_fields_on_unchanged_step(self) -> None:
        steps = [
            StepSpec(
                step_id="import",
                node_type="cardre.import_dataset",
                node_version="1",
                category="transform",
                params={"source": "data.csv"},
                params_hash=json_logical_hash({"source": "data.csv"}),
                parent_step_ids=[],
                branch_label="",
                position=0,
            ),
            StepSpec(
                step_id="manual-binning__br_a81f3c",
                node_type="cardre.manual_binning",
                node_version="1",
                category="refinement",
                params={"overrides": []},
                params_hash=json_logical_hash({"overrides": []}),
                parent_step_ids=["fine-classing", "variable-selection"],
                branch_label="Coarser bins",
                position=5,
                canonical_step_id="manual-binning",
                branch_id="br_a81f3c",
            ),
        ]
        new_steps = replace_step_params(steps, "import", {"source": "new_data.csv"})
        self.assertEqual(new_steps[0].canonical_step_id, "import")
        self.assertIsNone(new_steps[0].branch_id)
        self.assertEqual(new_steps[1].canonical_step_id, "manual-binning")
        self.assertEqual(new_steps[1].branch_id, "br_a81f3c")


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
# Slice 4: Baseline migration service
# ======================================================================

class BaselineMigrationTests(unittest.TestCase):

    def test_migrate_creates_baseline_branch(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG)
        pv_id = store.create_plan_version(plan_id, steps, description="v1")

        result = migrate_project_to_branch_model(store, project_id)

        self.assertEqual(result["branches_created"], 1)
        self.assertEqual(result["plan_versions_mapped"], 1)
        self.assertEqual(result["steps_mapped"], len(steps))

        branches = store.list_branches(project_id)
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["branch_type"], "baseline")
        self.assertEqual(branches[0]["name"], "Baseline")

    def test_migrate_creates_step_map_for_all_versions(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "Scorecard Pathway")

        v1_steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv1_id = store.create_plan_version(plan_id, v1_steps, description="v1")

        v2_steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:4])
        pv2_id = store.create_plan_version(plan_id, v2_steps, description="v2")

        result = migrate_project_to_branch_model(store, project_id)

        self.assertEqual(result["plan_versions_mapped"], 2)
        self.assertEqual(result["steps_mapped"], len(v1_steps) + len(v2_steps))

        branches = store.list_branches(project_id)
        branch_id = branches[0]["branch_id"]

        # Steps from v1
        v1_map = store.get_branch_step_map(branch_id, pv1_id)
        self.assertEqual(len(v1_map), len(v1_steps))

        # Steps from v2
        v2_map = store.get_branch_step_map(branch_id, pv2_id)
        self.assertEqual(len(v2_map), len(v2_steps))

    def test_migrate_idempotent(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        store.create_plan_version(plan_id, steps, description="v1")

        result1 = migrate_project_to_branch_model(store, project_id)
        self.assertEqual(result1["branches_created"], 1)

        result2 = migrate_project_to_branch_model(store, project_id)
        self.assertEqual(result2["branches_created"], 0)

        branches = store.list_branches(project_id)
        self.assertEqual(len(branches), 1)

    def test_migrate_excludes_hidden_import_plan(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        store.create_plan_version(
            store.create_plan(project_id, "__import__"),
            _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:1]),
            description="import",
        )
        plan_id = store.create_plan(project_id, "Scorecard Pathway")
        store.create_plan_version(plan_id, _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2]), description="v1")

        result = migrate_project_to_branch_model(store, project_id)
        self.assertEqual(result["branches_created"], 1)
        self.assertEqual(result["plan_versions_mapped"], 1)

    def test_migrate_does_not_rewrite_run_history(self) -> None:
        from cardre.executor import PlanExecutor
        from cardre.registry import NodeRegistry

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv_id = store.create_plan_version(plan_id, steps, description="v1")

        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        run_id = executor.run_plan_version(store, pv_id)
        original_run = store.get_run(run_id)
        original_run_steps = store.get_run_steps(run_id)

        migrate_project_to_branch_model(store, project_id)

        after_run = store.get_run(run_id)
        self.assertIsNotNone(after_run)
        self.assertEqual(after_run["status"], original_run["status"])
        self.assertEqual(after_run["started_at"], original_run["started_at"])
        self.assertEqual(after_run["finished_at"], original_run["finished_at"])

        after_run_steps = store.get_run_steps(run_id)
        self.assertEqual(len(after_run_steps), len(original_run_steps))
        for original, after in zip(original_run_steps, after_run_steps):
            self.assertEqual(original.run_step_id, after.run_step_id)
            self.assertEqual(original.status, after.status)
            self.assertEqual(original.execution_fingerprint, after.execution_fingerprint)

    def test_migrate_does_not_rewrite_artifacts(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv_id = store.create_plan_version(plan_id, steps, description="v1")

        from cardre.executor import PlanExecutor
        from cardre.registry import NodeRegistry
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        executor.run_plan_version(store, pv_id)

        original_artifacts = store.list_artifacts()

        migrate_project_to_branch_model(store, project_id)

        after_artifacts = store.list_artifacts()
        self.assertEqual(len(after_artifacts), len(original_artifacts))
        for oa, aa in zip(original_artifacts, after_artifacts):
            self.assertEqual(oa.artifact_id, aa.artifact_id)
            self.assertEqual(oa.physical_hash, aa.physical_hash)
            self.assertEqual(oa.logical_hash, aa.logical_hash)

    def test_migrate_branch_list_endpoint_works(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        store.create_plan_version(plan_id, steps, description="v1")

        migrate_project_to_branch_model(store, project_id)

        branches = store.list_branches(project_id)
        self.assertEqual(len(branches), 1)
        branch = branches[0]
        self.assertEqual(branch["name"], "Baseline")
        self.assertEqual(branch["branch_type"], "baseline")

    def test_migrate_creates_branch_with_correct_head_version(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "Scorecard Pathway")
        steps = _build_steps(PHASE2A_PATHWAY_STEPS_CONFIG[:2])
        pv1 = store.create_plan_version(plan_id, steps[:1], description="v1")
        pv2 = store.create_plan_version(plan_id, steps, description="v2")

        migrate_project_to_branch_model(store, project_id)

        branches = store.list_branches(project_id)
        branch = branches[0]
        self.assertEqual(branch["base_plan_version_id"], pv1)
        self.assertEqual(branch["head_plan_version_id"], pv2)
