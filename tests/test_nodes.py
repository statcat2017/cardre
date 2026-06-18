"""Tests for cardre.nodes — all node-level functional tests."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.executor import PlanExecutor
from cardre.nodes import (
    ApplyExclusionsNode,
    DefineModellingMetadataNode,
    DevelopmentSampleDefinitionNode,
    DummyApplyNode,
    DummyFitNode,
    ExplicitMissingOutlierTreatmentNode,
    ImportGermanCreditNode,
    ImportTabularDatasetNode,
    ProfileDatasetNode,
    SplitTrainTestOotNode,
    TechnicalManifestExportNode,
    ValidateBinaryTargetNode,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

from tests.helpers import (
    SAMPLE_GERMAN_CREDIT_LINES,
    _make_json_artifact,
    _make_train_artifact,
    make_sample_german_credit_file,
    make_sample_german_credit_zip,
    make_store,
)


# ======================================================================
# Helpers
# ======================================================================


def make_project_with_import(store: ProjectStore, tmp: Path) -> tuple[str, str]:
    project_id = store.create_project("test")
    plan_id = store.create_plan(project_id, "test-plan")
    source = make_sample_german_credit_file(tmp)

    steps = [
        StepSpec(
            step_id="import", node_type="cardre.import_fixture_uci_german_credit",
            node_version="1", category="transform",
            params={"source_path": str(source)},
            params_hash=json_logical_hash({"source_path": str(source)}),
            parent_step_ids=[], branch_label="", position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)
    reg = NodeRegistry.with_defaults()
    executor = PlanExecutor(reg)
    executor.run_plan_version(store, pv_id)
    return project_id, plan_id


def make_full_german_credit_download(tmp: Path) -> Path:
    """Create a larger German Credit fixture with 10 rows for more meaningful testing."""
    lines = SAMPLE_GERMAN_CREDIT_LINES * 5
    p = tmp / "german_full.data"
    p.write_text("\n".join(lines))
    return p


class GermanCreditImportTests(unittest.TestCase):

    def test_import_from_file_creates_parquet_artifact(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        source = make_sample_german_credit_file(tmp)

        step_spec = StepSpec(
            step_id="import-1",
            node_type="cardre.import_fixture_uci_german_credit",
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
            node_type="cardre.import_fixture_uci_german_credit",
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
            step_id="import-1", node_type="cardre.import_fixture_uci_german_credit",
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
            step_id="import-zip", node_type="cardre.import_fixture_uci_german_credit",
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

    def test_import_malformed_rows_fails(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        source = tmp / "malformed.data"
        source.write_text("1 2 3\n4 5 6 7\n")
        params = {"source_path": str(source)}
        step_spec = StepSpec(
            step_id="import-bad", node_type="cardre.import_fixture_uci_german_credit",
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
        with self.assertRaises(ValueError):
            node.run(ctx)

    def test_import_missing_source_path_fails_validation(self) -> None:
        node = ImportGermanCreditNode()
        errors = node.validate_params({})
        self.assertTrue(any("source_path" in e for e in errors))

    def test_import_unsupported_extension_fails(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        source = tmp / "data.csv"
        source.write_text("dummy")
        params = {"source_path": str(source)}
        step_spec = StepSpec(
            step_id="import-csv", node_type="cardre.import_fixture_uci_german_credit",
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
        with self.assertRaises(ValueError):
            node.run(ctx)

    def test_import_zip_without_german_data_fails(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test")
        import zipfile
        zpath = tmp / "empty.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("other.txt", "not german data")
        params = {"source_path": str(zpath)}
        step_spec = StepSpec(
            step_id="import-zip2", node_type="cardre.import_fixture_uci_german_credit",
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
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Profile + Split Regression Tests
# ======================================================================


class ProfileDatasetTests(unittest.TestCase):

    def test_all_null_numeric_column_does_not_crash(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "num_col": pl.Series([None, None, None], dtype=pl.Float64),
            "cat_col": ["a", "b", "c"],
        })
        art = _make_train_artifact(store, df, role="train")
        params = {}
        spec = StepSpec(
            step_id="profile", node_type="cardre.profile_dataset",
            node_version="1", category="transform",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[art],
            validated_params=params, runtime_metadata={},
        )
        node = ProfileDatasetNode()
        output = node.run(ctx)
        self.assertEqual(len(output.artifacts), 1)


class SplitRegressionTests(unittest.TestCase):

    def test_single_class_train_split_fails(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "x": [1.0, 2.0, 3.0],
            "target": pl.Series(["g", "g", "g"], dtype=pl.String),
        })
        art = _make_train_artifact(store, df, role="input")
        meta_art = _make_json_artifact(store, {
            "target_column": "target",
            "good_values": ["g"], "bad_values": ["b"],
        }, stem="meta")
        params = {
            "strategy": "random_stratified",
            "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
            "target_column": "target", "random_seed": 42,
        }
        spec = StepSpec(
            step_id="split", node_type="cardre.split_train_test_oot",
            node_version="2", category="transform",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[art],
            validated_params=params, runtime_metadata={},
        )
        node = SplitTrainTestOotNode()
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Slice 4: Node Registry + Contracts
# ======================================================================


class NodeRegistryTests(unittest.TestCase):

    def test_register_and_resolve(self) -> None:
        reg = NodeRegistry()
        reg.register(ImportGermanCreditNode)
        cls = reg.resolve("cardre.import_fixture_uci_german_credit")
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
        self.assertEqual(node.node_type, "cardre.import_fixture_uci_german_credit")
        self.assertEqual(node.version, "1")
        self.assertEqual(node.category, "transform")

    def test_generic_import_node_defines_contract(self) -> None:
        node = ImportTabularDatasetNode()
        self.assertEqual(node.node_type, "cardre.import_dataset")
        self.assertEqual(node.version, "1")
        self.assertEqual(node.category, "transform")

    def test_default_registry_has_all_proof_nodes(self) -> None:
        reg = NodeRegistry.with_defaults()
        for nt in [
            "cardre.import_dataset",
            "cardre.import_fixture_uci_german_credit",
            "cardre.profile_dataset",
            "cardre.validate_binary_target",
            "cardre.split_train_test_oot",
            "cardre.dummy_fit",
            "cardre.dummy_apply",
        ]:
            self.assertTrue(reg.has(nt), f"Missing {nt}")


class DefineModellingMetadataTests(unittest.TestCase):

    def test_metadata_artifact_created(self) -> None:
        store, tmp = make_store()
        project_id, plan_id = make_project_with_import(store, tmp)
        import_artifact = store.list_artifacts()[0]

        step_spec = StepSpec(
            step_id="define-metadata", node_type="cardre.define_modelling_metadata",
            node_version="1", category="transform",
            params={
                "target_column": "credit_risk_class",
                "good_values": ["1"],
                "bad_values": ["2"],
                "indeterminate_values": [],
                "population": "", "product": "", "segment": "",
                "observation_window": None, "performance_window": None,
            },
            params_hash=json_logical_hash({
                "target_column": "credit_risk_class",
                "good_values": ["1"], "bad_values": ["2"],
                "indeterminate_values": [], "population": "",
                "product": "", "segment": "",
                "observation_window": None, "performance_window": None,
            }),
            parent_step_ids=["import"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[import_artifact],
            validated_params=step_spec.params, runtime_metadata={},
        )
        node = DefineModellingMetadataNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.role, "definition")
        self.assertEqual(artifact.artifact_type, "definition")

        payload = json.loads(store.artifact_path(artifact).read_text())
        self.assertEqual(payload["target_column"], "credit_risk_class")
        self.assertEqual(payload["good_values"], ["1"])
        self.assertEqual(payload["bad_values"], ["2"])

    def test_missing_target_column_fails(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"col1": [1, 2, 3]})
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test-data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        mock_artifact = ArtifactRef(
            artifact_id="a1", artifact_type="dataset", role="input",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(mock_artifact)

        step_spec = StepSpec(
            step_id="meta", node_type="cardre.define_modelling_metadata",
            node_version="1", category="transform",
            params={
                "target_column": "nonexistent_col",
                "good_values": ["1"], "bad_values": ["2"],
            },
            params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[mock_artifact],
            validated_params=step_spec.params, runtime_metadata={},
        )
        node = DefineModellingMetadataNode()
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Workstream 3: Apply Exclusions
# ======================================================================


class ApplyExclusionsTests(unittest.TestCase):

    def test_exclusion_filters_rows(self) -> None:
        store, tmp = make_store()
        project_id, plan_id = make_project_with_import(store, tmp)
        import_artifact = store.list_artifacts()[0]
        df = pl.read_parquet(store.artifact_path(import_artifact))
        original_count = df.height

        params = {
            "rules": [
                {
                    "column": "age_years",
                    "operator": ">=",
                    "value": 18,
                    "reason": "Adult lending population",
                }
            ]
        }
        step_spec = StepSpec(
            step_id="apply-exclusions", node_type="cardre.apply_exclusions",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["import"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[import_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = ApplyExclusionsNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        artifact = output.artifacts[0]
        filtered_df = pl.read_parquet(store.artifact_path(artifact))
        self.assertLessEqual(filtered_df.height, original_count)

    def test_exclusion_no_rules_passthrough(self) -> None:
        store, tmp = make_store()
        project_id, plan_id = make_project_with_import(store, tmp)
        import_artifact = store.list_artifacts()[0]

        params = {"rules": []}
        step_spec = StepSpec(
            step_id="apply-exclusions", node_type="cardre.apply_exclusions",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["import"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[import_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = ApplyExclusionsNode()
        output = node.run(ctx)

        artifact = output.artifacts[0]
        filtered_df = pl.read_parquet(store.artifact_path(artifact))
        self.assertGreater(filtered_df.height, 0)

    def test_exclusion_bad_operator_fails(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"age": [18, 25, 30]})
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test-data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        mock_artifact = ArtifactRef(
            artifact_id="a1", artifact_type="dataset", role="input",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(mock_artifact)

        params = {
            "rules": [{"column": "age", "operator": "bad_op", "value": 18, "reason": "test"}]
        }
        step_spec = StepSpec(
            step_id="excl", node_type="cardre.apply_exclusions",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[mock_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = ApplyExclusionsNode()
        with self.assertRaises(ValueError):
            node.run(ctx)

    def test_exclusion_removes_matching_rows(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"age": [15, 18, 25, 30], "score": [1, 2, 3, 4]})
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test-data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        mock_artifact = ArtifactRef(
            artifact_id="a1", artifact_type="dataset", role="input",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(mock_artifact)

        params = {
            "rules": [{"column": "age", "operator": ">=", "value": 18, "reason": "Adults only"}]
        }
        step_spec = StepSpec(
            step_id="excl", node_type="cardre.apply_exclusions",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[mock_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = ApplyExclusionsNode()
        output = node.run(ctx)
        result_df = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        # Rows with age >= 18 should be REMOVED (exclusion rule)
        self.assertEqual(result_df.height, 1)
        self.assertEqual(result_df["age"][0], 15)


# ======================================================================
# Workstream 4: Development Sample Definition
# ======================================================================


class DevelopmentSampleDefinitionTests(unittest.TestCase):

    def test_sample_definition_created(self) -> None:
        store, tmp = make_store()
        project_id, plan_id = make_project_with_import(store, tmp)
        import_artifact = store.list_artifacts()[0]

        params = {
            "sample_method": "full_population",
            "weight_column": None,
            "population_bad_rate": None,
            "prior_probability_adjustment": None,
        }
        step_spec = StepSpec(
            step_id="sample-def", node_type="cardre.development_sample_definition",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["import"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[import_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = DevelopmentSampleDefinitionNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.role, "definition")
        payload = json.loads(store.artifact_path(artifact).read_text())
        self.assertEqual(payload["sample_method"], "full_population")


# ======================================================================
# Workstream 5: Explicit Missing/Outlier Treatment
# ======================================================================


class ExplicitMissingOutlierTreatmentTests(unittest.TestCase):

    def test_treatment_passthrough(self) -> None:
        store, tmp = make_store()
        project_id, plan_id = make_project_with_import(store, tmp)
        import_artifact = store.list_artifacts()[0]

        df = pl.read_parquet(store.artifact_path(import_artifact))
        # Create a mock treated output by taking all 3 roles from the import
        mock_artifacts = [
            import_artifact,
        ]

        params = {"imputations": {}, "caps": {}, "floors": {}}
        step_spec = StepSpec(
            step_id="treatment", node_type="cardre.explicit_missing_outlier_treatment",
            node_version="1", category="apply",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["split"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=mock_artifacts,
            validated_params=params, runtime_metadata={},
        )
        node = ExplicitMissingOutlierTreatmentNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        self.assertEqual(output.artifacts[0].role, "input")


class TechnicalManifestTests(unittest.TestCase):

    def test_manifest_stub_created(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")

        source = make_sample_german_credit_file(tmp)
        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_fixture_uci_german_credit",
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

        all_artifacts = store.list_artifacts()
        import_artifact = all_artifacts[0]

        params = {}
        step_spec = StepSpec(
            step_id="manifest", node_type="cardre.technical_manifest_export",
            node_version="1", category="transform",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        run_steps = store.get_run_steps(run_id)
        ctx = ExecutionContext(
            store=store, run_id=run_id, plan_version_id=pv_id,
            step_spec=step_spec,
            parent_run_steps=run_steps,
            input_artifacts=[import_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = TechnicalManifestExportNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.role, "manifest")
        self.assertEqual(artifact.artifact_type, "manifest")

        payload = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("run", payload)
        self.assertIn("steps", payload)
        self.assertIn("artifacts", payload)


class BlockerVerificationTests(unittest.TestCase):

    def test_blank_target_column_fails(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({"col1": [1, 2]})
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        art = ArtifactRef(
            artifact_id="a1", artifact_type="dataset", role="input",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(art)

        params = {"target_column": "", "good_values": ["1"], "bad_values": ["2"]}
        spec = StepSpec(
            step_id="meta", node_type="cardre.define_modelling_metadata",
            node_version="1", category="transform",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[art], validated_params=params, runtime_metadata={},
        )
        node = DefineModellingMetadataNode()
        with self.assertRaises(ValueError):
            node.run(ctx)
