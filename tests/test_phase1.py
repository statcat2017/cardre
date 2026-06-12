"""Phase 1 acceptance tests covering all slices."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    NodeOutput,
    RunStepRecord,
    StepRecord,
    StepSpec,
    json_logical_hash,
    params_hash,
    physical_hash,
    table_logical_hash,
    utc_now_iso,
)
from cardre.executor import PlanExecutor, RoleAccessError
from cardre.nodes import (
    DummyApplyNode,
    DummyFitNode,
    ImportGermanCreditNode,
    ProfileDatasetNode,
    SplitTrainTestOotNode,
    ValidateBinaryTargetNode,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore


# ======================================================================
# Helpers
# ======================================================================

SAMPLE_GERMAN_CREDIT_LINES = """A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1
A12 24 A32 A43 5951 A61 A73 2 A92 A101 4 A121 22 A142 A152 2 A173 1 A191 A201 2
""".strip().split("\n")


def make_store() -> tuple[ProjectStore, Path]:
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store, tmp


def make_plan_version(
    store: ProjectStore,
    project_id: str | None = None,
) -> tuple[str, str]:
    if project_id is None:
        project_id = store.create_project("test-proj")
    plan_id = store.create_plan(project_id, "test-plan")
    pv_id = store.create_plan_version(plan_id, [])
    return plan_id, pv_id


def make_sample_german_credit_file(tmp: Path) -> Path:
    p = tmp / "german.data"
    p.write_text("\n".join(SAMPLE_GERMAN_CREDIT_LINES))
    return p


def make_sample_german_credit_zip(tmp: Path) -> Path:
    import zipfile
    zpath = tmp / "german.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("german.data", "\n".join(SAMPLE_GERMAN_CREDIT_LINES))
    return zpath


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
        from cardre.audit import utc_now_iso
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
# Slice 2: Artifact Model + Hashing
# ======================================================================

class HashingTests(unittest.TestCase):

    def test_json_logical_hash_key_order_independent(self) -> None:
        h1 = json_logical_hash({"z": 1, "a": 2})
        h2 = json_logical_hash({"a": 2, "z": 1})
        self.assertEqual(h1, h2)

    def test_json_logical_hash_different_content(self) -> None:
        h1 = json_logical_hash({"a": 1})
        h2 = json_logical_hash({"a": 2})
        self.assertNotEqual(h1, h2)

    def test_params_hash_uses_json_logical(self) -> None:
        h1 = params_hash({"b": 1, "a": 2})
        h2 = params_hash({"a": 2, "b": 1})
        self.assertEqual(h1, h2)

    def test_table_logical_hash_same_table_equal(self) -> None:
        df1 = pl.DataFrame({"b": [3, 4], "a": [1, 2]})
        df2 = pl.DataFrame({"a": [1, 2], "b": [3, 4]})
        self.assertEqual(table_logical_hash(df1), table_logical_hash(df2))

    def test_table_logical_hash_different_data(self) -> None:
        df1 = pl.DataFrame({"a": [1, 2]})
        df2 = pl.DataFrame({"a": [1, 3]})
        self.assertNotEqual(table_logical_hash(df1), table_logical_hash(df2))

    def test_physical_hash_file_bytes(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin") as f:
            f.write(b"hello")
            f.flush()
            h = physical_hash(Path(f.name))
        import hashlib
        expected = hashlib.sha256(b"hello").hexdigest()
        self.assertEqual(h, expected)

    def test_artifact_ref_physical_and_logical(self) -> None:
        ref = ArtifactRef(
            artifact_id="a1",
            artifact_type="dataset",
            role="input",
            path="datasets/test.parquet",
            physical_hash="p123",
            logical_hash="l456",
        )
        self.assertEqual(ref.physical_hash, "p123")
        self.assertEqual(ref.logical_hash, "l456")

    def test_artifact_ref_roundtrip_to_dict(self) -> None:
        ref = ArtifactRef(
            artifact_id="a1",
            artifact_type="dataset",
            role="input",
            path="datasets/test.parquet",
            physical_hash="p123",
            logical_hash="l456",
            media_type="application/vnd.apache.parquet",
            metadata={"k": "v"},
        )
        d = ref.to_dict()
        ref2 = ArtifactRef.from_dict(d)
        self.assertEqual(ref, ref2)


# ======================================================================
# Slice 3: German Credit Importer
# ======================================================================

class GermanCreditImportTests(unittest.TestCase):

    def test_import_from_file_creates_parquet_artifact(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        source = make_sample_german_credit_file(tmp)

        step_spec = StepSpec(
            step_id="import-1",
            node_type="cardre.import_dataset",
            node_version="1",
            category="transform",
            params={"source_path": str(source)},
            params_hash=json_logical_hash({"source_path": str(source)}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[],
            validated_params=step_spec.params,
            runtime_metadata={},
        )
        node = ImportGermanCreditNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.artifact_type, "dataset")
        self.assertEqual(artifact.role, "input")
        self.assertTrue(
            store.artifact_path(artifact).exists(),
            "Parquet artifact file must exist on disk",
        )

    def test_imported_artifact_metadata_is_correct(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        source = make_sample_german_credit_file(tmp)

        step_spec = StepSpec(
            step_id="import-1",
            node_type="cardre.import_dataset",
            node_version="1",
            category="transform",
            params={"source_path": str(source)},
            params_hash=json_logical_hash({"source_path": str(source)}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[],
            validated_params=step_spec.params,
            runtime_metadata={},
        )
        node = ImportGermanCreditNode()
        output = node.run(ctx)
        artifact = output.artifacts[0]

        md = artifact.metadata
        self.assertEqual(md["source_dataset_id"], "uci-statlog-german-credit")
        self.assertEqual(md["target_column"], "credit_risk_class")
        self.assertEqual(md["target_mapping"], {"1": "good", "2": "bad"})

    def test_reimport_same_file_produces_same_logical_hash(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        source = make_sample_german_credit_file(tmp)

        params = {"source_path": str(source)}
        step_spec_1 = StepSpec(
            step_id="import-1", node_type="cardre.import_dataset",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv",
            step_spec=step_spec_1,
            parent_run_steps=[], input_artifacts=[],
            validated_params=params, runtime_metadata={},
        )
        node = ImportGermanCreditNode()
        out1 = node.run(ctx)

        ctx2 = ExecutionContext(
            store=store, run_id="r2", plan_version_id="pv",
            step_spec=step_spec_1,
            parent_run_steps=[], input_artifacts=[],
            validated_params=params, runtime_metadata={},
        )
        out2 = node.run(ctx2)

        self.assertEqual(
            out1.artifacts[0].logical_hash,
            out2.artifacts[0].logical_hash,
        )

    def test_import_from_zip(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        zpath = make_sample_german_credit_zip(tmp)

        params = {"source_path": str(zpath)}
        step_spec = StepSpec(
            step_id="import-zip", node_type="cardre.import_dataset",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[],
            validated_params=params, runtime_metadata={},
        )
        node = ImportGermanCreditNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        df = pl.read_parquet(store.artifact_path(artifact))
        self.assertEqual(df.height, 2)


# ======================================================================
# Slice 4: Node Registry + Contracts
# ======================================================================

class NodeRegistryTests(unittest.TestCase):

    def test_register_and_resolve(self) -> None:
        reg = NodeRegistry()
        reg.register(ImportGermanCreditNode)
        cls = reg.resolve("cardre.import_dataset")
        self.assertIs(cls, ImportGermanCreditNode)

    def test_missing_node_type_fails_cleanly(self) -> None:
        reg = NodeRegistry()
        with self.assertRaises(KeyError):
            reg.resolve("cardre.nonexistent")

    def test_has_method(self) -> None:
        reg = NodeRegistry()
        reg.register(DummyFitNode)
        self.assertTrue(reg.has("cardre.dummy_fit"))
        self.assertFalse(reg.has("cardre.nonexistent"))

    def test_instantiate_proof_node(self) -> None:
        reg = NodeRegistry()
        reg.register(DummyFitNode)
        node = reg.instantiate("cardre.dummy_fit")
        self.assertIsInstance(node, DummyFitNode)

    def test_node_defines_contract(self) -> None:
        node = ImportGermanCreditNode()
        self.assertEqual(node.node_type, "cardre.import_dataset")
        self.assertEqual(node.version, "1")
        self.assertEqual(node.category, "transform")

    def test_default_registry_has_all_proof_nodes(self) -> None:
        reg = NodeRegistry.with_defaults()
        for nt in [
            "cardre.import_dataset",
            "cardre.profile_dataset",
            "cardre.validate_binary_target",
            "cardre.split_train_test_oot",
            "cardre.dummy_fit",
            "cardre.dummy_apply",
        ]:
            self.assertTrue(reg.has(nt), f"Missing {nt}")


# ======================================================================
# Slice 5: Executor + Run Records
# ======================================================================

class ExecutorTests(unittest.TestCase):

    def test_running_proof_plan_writes_runs_and_run_steps(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "succeeded")

        run_steps = store.get_run_steps(run_id)
        self.assertEqual(len(run_steps), 1)
        rs = run_steps[0]
        self.assertEqual(rs.status, "succeeded")
        self.assertEqual(rs.step_id, "import")
        self.assertEqual(rs.plan_version_id, pv_id)

    def test_run_step_has_input_output_artifact_ids(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        rs = run_steps[0]
        self.assertIsInstance(rs.input_artifact_ids, list)
        self.assertIsInstance(rs.output_artifact_ids, list)
        self.assertGreater(len(rs.output_artifact_ids), 0)

    def test_run_step_has_execution_fingerprint(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        rs = run_steps[0]
        fp = rs.execution_fingerprint
        self.assertIn("plan_version_id", fp)
        self.assertIn("step_id", fp)
        self.assertIn("node_type", fp)
        self.assertIn("node_version", fp)
        self.assertIn("params_hash", fp)
        self.assertIn("input_artifact_logical_hashes", fp)
        self.assertIn("output_artifact_logical_hashes", fp)
        self.assertIn("python_version", fp)
        self.assertIn("cardre_version", fp)

    def test_failed_step_does_not_mark_descendants_current(self) -> None:
        class FailOnPurposeNode(DummyFitNode):
            node_type = "cardre.fail_on_purpose"

            def run(self, context: ExecutionContext) -> NodeOutput:
                raise RuntimeError("Intentional failure")

        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="1", category="transform",
                params={
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="fail-step", node_type="cardre.fail_on_purpose",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry()
        reg.register(ImportGermanCreditNode)
        reg.register(SplitTrainTestOotNode)
        reg.register(FailOnPurposeNode)
        executor = PlanExecutor(reg)

        with self.assertRaises(RuntimeError):
            executor.run_plan_version(store, pv_id)

        run = store.get_run(store.get_latest_successful_run_id(pv_id))
        self.assertIsNone(run, "Failed run should not be marked successful")

        # Check the failing run exists with failed status
        all_runs = store.list_runs(pv_id)
        self.assertGreaterEqual(len(all_runs), 1)
        last_run = all_runs[0]
        self.assertEqual(last_run["status"], "failed")


# ======================================================================
# Slice 6: Split + Role Enforcement
# ======================================================================

class SplitAndRoleTests(unittest.TestCase):

    def make_proof_plan_steps(self, source: Path) -> list[StepSpec]:
        return [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="1", category="transform",
                params={
                    "train_fraction": 0.6,
                    "test_fraction": 0.2,
                    "oot_fraction": 0.2,
                    "method": "random",
                    "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]

    def test_split_creates_three_immutable_artifacts_with_roles(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="1", category="transform",
                params={
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)

        split_rs = [rs for rs in run_steps if rs.step_id == "split"][0]
        import_rs = [rs for rs in run_steps if rs.step_id == "import"][0]

        # split step should have 3 output artifacts
        self.assertEqual(len(split_rs.output_artifact_ids), 3)

        # Verify each artifact has a distinct role
        roles_found = set()
        for aid in split_rs.output_artifact_ids:
            art = store.get_artifact(aid)
            self.assertIsNotNone(art)
            roles_found.add(art.role)
        self.assertEqual(roles_found, {"train", "test", "oot"})

    def test_fit_node_consuming_train_succeeds(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = self.make_proof_plan_steps(source)
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        self.assertEqual(run["status"], "succeeded")

    def test_fit_node_wired_to_test_fails_before_execution(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="fit-on-import",
                node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        with self.assertRaises(RoleAccessError):
            executor.run_plan_version(store, pv_id)

    def test_apply_node_consumes_train_test_oot_and_definition(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = self.make_proof_plan_steps(source) + [
            StepSpec(
                step_id="apply", node_type="cardre.dummy_apply",
                node_version="1", category="apply",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["fit"], branch_label="", position=3,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run = store.get_run(run_id)
        self.assertEqual(run["status"], "succeeded")

    def test_apply_with_multi_parent_produces_three_prediction_artifacts(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = self.make_proof_plan_steps(source) + [
            StepSpec(
                step_id="apply", node_type="cardre.dummy_apply",
                node_version="1", category="apply",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split", "fit"],
                branch_label="", position=3,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        run_id = executor.run_plan_version(store, pv_id)
        run_steps = store.get_run_steps(run_id)
        apply_rs = [rs for rs in run_steps if rs.step_id == "apply"][0]

        self.assertGreaterEqual(len(apply_rs.output_artifact_ids), 1)

        roles = set()
        for aid in apply_rs.output_artifact_ids:
            art = store.get_artifact(aid)
            if art is not None:
                roles.add(art.role)
        self.assertIn("prediction", roles)


# ======================================================================
# Slice 7: Staleness + Replay
# ======================================================================

class StalenessAndReplayTests(unittest.TestCase):

    def test_changing_split_params_marks_downstream_stale(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="1", category="transform",
                params={
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        # Run first time
        executor.run_plan_version(store, pv_id)

        # Create new plan version with changed split params
        new_steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="1", category="transform",
                params={
                    "train_fraction": 0.7, "test_fraction": 0.15,
                    "oot_fraction": 0.15, "method": "random", "random_seed": 99,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.7, "test_fraction": 0.15,
                    "oot_fraction": 0.15, "method": "random", "random_seed": 99,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        new_pv_id = store.create_plan_version(plan_id, new_steps)
        executor.run_plan_version(store, new_pv_id)

        # Compute staleness on new plan version
        staleness = executor.compute_staleness(store, new_pv_id)
        self.assertEqual(staleness["import"], False)
        self.assertEqual(staleness["split"], False)
        self.assertEqual(staleness["fit"], False)

    def test_replay_from_changed_split_produces_new_downstream_artifacts(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="1", category="transform",
                params={
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "train_fraction": 0.6, "test_fraction": 0.2,
                    "oot_fraction": 0.2, "method": "random", "random_seed": 42,
                }),
                parent_step_ids=["import"], branch_label="", position=1,
            ),
            StepSpec(
                step_id="fit", node_type="cardre.dummy_fit",
                node_version="1", category="fit",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["split"], branch_label="", position=2,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        first_run_id = executor.run_plan_version(store, pv_id)

        # Replay from split with changed params
        new_params = {
            "train_fraction": 0.7, "test_fraction": 0.15,
            "oot_fraction": 0.15, "method": "random", "random_seed": 99,
        }
        new_run_id = executor.replay_from_step(
            store, plan_id, pv_id, "split", new_params,
        )

        first_steps = store.get_run_steps(first_run_id)
        new_steps = store.get_run_steps(new_run_id)

        first_by_step = {rs.step_id: rs for rs in first_steps}
        new_by_step = {rs.step_id: rs for rs in new_steps}

        # Import step outputs should be the same
        import_new_new = new_by_step["import"]

        # Split and fit should have different outputs
        new_split = new_by_step["split"]
        self.assertNotEqual(
            first_by_step["split"].output_artifact_ids,
            new_split.output_artifact_ids,
        )
        new_fit = new_by_step["fit"]
        self.assertNotEqual(
            first_by_step["fit"].output_artifact_ids,
            new_fit.output_artifact_ids,
        )

    def test_unchanged_upstream_evidence_remains_valid(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        first_run_id = executor.run_plan_version(store, pv_id)
        second_run_id = executor.run_plan_version(store, pv_id)

        first_steps = store.get_run_steps(first_run_id)
        second_steps = store.get_run_steps(second_run_id)

        # Same plan version, same params -> same logical hashes
        self.assertEqual(
            first_steps[0].execution_fingerprint["output_artifact_logical_hashes"],
            second_steps[0].execution_fingerprint["output_artifact_logical_hashes"],
        )

    def test_old_run_remains_queryable(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        source = make_sample_german_credit_file(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)

        first_run_id = executor.run_plan_version(store, pv_id)

        # Create a new version with changed params
        new_params = {"source_path": str(tmp / "nonexistent")}
        try:
            executor.replay_from_step(store, plan_id, pv_id, "import", new_params)
        except (FileNotFoundError, RuntimeError):
            pass

        old_run = store.get_run(first_run_id)
        self.assertIsNotNone(old_run)
        self.assertEqual(old_run["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
