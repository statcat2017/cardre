"""Tests for cardre.nodes — all node-level functional tests."""

from __future__ import annotations

import io
import json
import unittest
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    RunStepRecord,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
    utc_now_iso,
)
from cardre.executor import PlanExecutor
from cardre.nodes import (
    ApplyExclusionsNode,
    ApplyModelNode,
    DefineModellingMetadataNode,
    DevelopmentSampleDefinitionNode,
    DummyFitNode,
    ExplicitMissingOutlierTreatmentNode,
    ImportGermanCreditNode,
    ImportTabularDatasetNode,
    LogisticRegressionNode,
    ProfileDatasetNode,
    ScoreScalingNode,
    SplitTrainTestOotNode,
    TechnicalManifestExportNode,
    CutoffAnalysisNode,
    ValidationMetricsNode,
    VariableSelectionNode,
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


def _guard_json_loads_for_node(module_suffix: str):
    original = json.loads

    def _loads(*args, **kwargs):
        caller = sys._getframe(1)
        if caller.f_code.co_filename.endswith(module_suffix):
            raise AssertionError("raw json read should not be used")
        return original(*args, **kwargs)

    return _loads


def _save_run_step(
    store: ProjectStore,
    *,
    run_id: str,
    plan_version_id: str,
    step_id: str,
    node_type: str,
    input_artifacts: list[ArtifactRef],
    output_artifacts: list[ArtifactRef],
    execution_fingerprint: dict[str, Any] | None = None,
) -> RunStepRecord:
    rs = RunStepRecord(
        run_step_id=f"{step_id}-rs",
        run_id=run_id,
        step_id=step_id,
        plan_version_id=plan_version_id,
        status="succeeded",
        started_at=utc_now_iso(),
        finished_at=utc_now_iso(),
        input_artifact_ids=[a.artifact_id for a in input_artifacts],
        output_artifact_ids=[a.artifact_id for a in output_artifacts],
        execution_fingerprint=execution_fingerprint or {"node_type": node_type},
        warnings=[],
        errors=[],
    )
    store.save_run_step(rs)
    return rs


class GermanCreditImportTests(unittest.TestCase):

    def test_import_from_file_creates_parquet_artifact(self) -> None:
        store, tmp = make_store()
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
        _make_json_artifact(store, {
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

    def test_manifest_includes_real_evidence_outputs(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        plan_version_id = store.create_plan_version(plan_id, [])
        run_id = store.create_run(plan_version_id)

        iv_df = pl.DataFrame({
            "variable": ["x_woe"],
            "iv": [0.3],
            "bin_count": [2],
            "zero_cell_count": [0],
            "warning_count": [0],
        })
        iv_art = write_parquet_artifact(
            store,
            artifact_type="report",
            role="report",
            stem="iv",
            frame=iv_df,
            metadata={},
        )
        clustering = {
            "schema_version": "cardre.variable_clustering_evidence.v1",
            "method": "correlation_threshold",
            "input_representation": "raw_train",
            "similarity_metric": "pearson",
            "absolute_correlation": True,
            "threshold": 0.7,
            "missing_handling": "pairwise",
            "candidate_limit": 50,
            "representative_rule": "highest_iv",
            "clusters": [],
            "singleton_variables": ["x_woe"],
            "warnings": [],
        }
        clust_art = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem="clustering",
            payload=clustering,
            metadata={},
        )
        sel_params = {
            "min_iv": 0.02,
            "max_variables": 15,
            "cluster_representative_rule": "none",
            "cluster_representative_overrides": [],
        }
        sel_ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=StepSpec(
                step_id="variable-selection",
                node_type="cardre.variable_selection",
                node_version="1",
                category="selection",
                params=sel_params,
                params_hash=json_logical_hash(sel_params),
                parent_step_ids=[],
                branch_label="",
                position=0,
            ),
            parent_run_steps=[],
            input_artifacts=[iv_art, clust_art],
            validated_params=sel_params,
            runtime_metadata={},
        )
        sel_out = VariableSelectionNode().run(sel_ctx)
        _save_run_step(
            store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_id="variable-selection",
            node_type="cardre.variable_selection",
            input_artifacts=[iv_art, clust_art],
            output_artifacts=sel_out.artifacts,
        )

        train_df = pl.DataFrame({
            "x_woe": [0.5, -0.3, 0.5, -0.3],
            "target": ["bad", "good", "bad", "good"],
        })
        train_art = write_parquet_artifact(
            store,
            artifact_type="dataset",
            role="train",
            stem="train",
            frame=train_df,
            metadata={},
        )
        def_art = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem="definition",
            payload={
                "target_column": "target",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={},
        )
        lr_params = {"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "random_seed": 42}
        lr_ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=StepSpec(
                step_id="logistic-regression",
                node_type="cardre.logistic_regression",
                node_version="1",
                category="fit",
                params=lr_params,
                params_hash=json_logical_hash(lr_params),
                parent_step_ids=[],
                branch_label="",
                position=1,
            ),
            parent_run_steps=[],
            input_artifacts=[train_art, def_art],
            validated_params=lr_params,
            runtime_metadata={},
        )
        lr_out = LogisticRegressionNode().run(lr_ctx)
        _save_run_step(
            store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_id="logistic-regression",
            node_type="cardre.logistic_regression",
            input_artifacts=[train_art, def_art],
            output_artifacts=lr_out.artifacts,
        )

        model_art = lr_out.artifacts[0]
        bin_def = {
            "variables": [{
                "variable": "x",
                "kind": "numeric",
                "bins": [
                    {"bin_id": "x_b1", "label": "Low", "lower": 0, "upper": 10,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 50, "good_count": 40, "bad_count": 10},
                    {"bin_id": "x_b2", "label": "High", "lower": 10, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 50, "good_count": 30, "bad_count": 20},
                ],
            }],
            "warnings": [],
        }
        bin_art = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem="bins",
            payload=bin_def,
            metadata={},
        )
        woe_df = pl.DataFrame({
            "variable": ["x", "x"],
            "bin_id": ["x_b1", "x_b2"],
            "label": ["Low", "High"],
            "row_count": [50, 50], "good_count": [40, 30], "bad_count": [10, 20],
            "good_distribution": [0.5, 0.5], "bad_distribution": [0.5, 0.5],
            "woe": [0.3, -0.2], "iv_component": [0.1, 0.05],
        })
        woe_art = write_parquet_artifact(
            store,
            artifact_type="report",
            role="report",
            stem="woe",
            frame=woe_df,
            metadata={},
        )
        score_params = {
            "base_score": 600,
            "base_odds": 50.0,
            "points_to_double_odds": 20,
            "higher_score_is_lower_risk": True,
        }
        ss_ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=StepSpec(
                step_id="score-scaling",
                node_type="cardre.score_scaling",
                node_version="1",
                category="fit",
                params=score_params,
                params_hash=json_logical_hash(score_params),
                parent_step_ids=[],
                branch_label="",
                position=2,
            ),
            parent_run_steps=[],
            input_artifacts=[model_art, bin_art, woe_art],
            validated_params=score_params,
            runtime_metadata={},
        )
        ss_out = ScoreScalingNode().run(ss_ctx)
        _save_run_step(
            store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_id="score-scaling",
            node_type="cardre.score_scaling",
            input_artifacts=[model_art, bin_art, woe_art],
            output_artifacts=ss_out.artifacts,
        )

        apply_ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=StepSpec(
                step_id="apply-model",
                node_type="cardre.apply_model",
                node_version="1",
                category="apply",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=[],
                branch_label="",
                position=3,
            ),
            parent_run_steps=[],
            input_artifacts=[train_art, model_art],
            validated_params={},
            runtime_metadata={},
        )
        apply_out = ApplyModelNode().run(apply_ctx)
        _save_run_step(
            store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_id="apply-model",
            node_type="cardre.apply_model",
            input_artifacts=[train_art, model_art],
            output_artifacts=apply_out.artifacts,
        )

        scored_df = pl.read_parquet(store.artifact_path(apply_out.artifacts[0]))
        scored_df = scored_df.with_columns(
            pl.Series("score", (1.0 - scored_df["predicted_bad_probability"]) * 1000, dtype=pl.Float64)
        )
        scored_art = write_parquet_artifact(
            store,
            artifact_type="dataset",
            role="train",
            stem="scored",
            frame=scored_df,
            metadata={},
        )

        val_ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=StepSpec(
                step_id="validation-metrics",
                node_type="cardre.validation_metrics",
                node_version="1",
                category="apply",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=[],
                branch_label="",
                position=4,
            ),
            parent_run_steps=[],
            input_artifacts=[scored_art, def_art],
            validated_params={},
            runtime_metadata={},
        )
        val_out = ValidationMetricsNode().run(val_ctx)
        _save_run_step(
            store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_id="validation-metrics",
            node_type="cardre.validation_metrics",
            input_artifacts=[scored_art, def_art],
            output_artifacts=val_out.artifacts,
        )

        cutoff_ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=StepSpec(
                step_id="cutoff-analysis",
                node_type="cardre.cutoff_analysis",
                node_version="1",
                category="apply",
                params={"band_count": 2},
                params_hash=json_logical_hash({"band_count": 2}),
                parent_step_ids=[],
                branch_label="",
                position=5,
            ),
            parent_run_steps=[],
            input_artifacts=[scored_art, def_art],
            validated_params={"band_count": 2},
            runtime_metadata={},
        )
        cutoff_out = CutoffAnalysisNode().run(cutoff_ctx)
        _save_run_step(
            store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_id="cutoff-analysis",
            node_type="cardre.cutoff_analysis",
            input_artifacts=[scored_art, def_art],
            output_artifacts=cutoff_out.artifacts,
        )

        manifest_params: dict[str, Any] = {}
        manifest_ctx = ExecutionContext(
            store=store,
            run_id=run_id,
            plan_version_id=plan_version_id,
            step_spec=StepSpec(
                step_id="manifest",
                node_type="cardre.technical_manifest_export",
                node_version="1",
                category="transform",
                params=manifest_params,
                params_hash=json_logical_hash(manifest_params),
                parent_step_ids=[],
                branch_label="",
                position=6,
            ),
            parent_run_steps=store.get_run_steps(run_id),
            input_artifacts=[],
            validated_params=manifest_params,
            runtime_metadata={},
        )
        with patch("cardre.nodes.build.export.json.loads", _guard_json_loads_for_node("cardre/nodes/build/export.py")):
            manifest_out = TechnicalManifestExportNode().run(manifest_ctx)

        self.assertEqual(len(manifest_out.artifacts), 1)
        artifact = manifest_out.artifacts[0]
        self.assertEqual(artifact.role, "manifest")
        self.assertEqual(artifact.artifact_type, "manifest")

        payload = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("model", payload)
        self.assertIn("scorecard", payload)
        self.assertIn("selected_variables", payload)
        self.assertIn("validation_metrics", payload)
        self.assertIn("cutoff_analysis", payload)
        self.assertTrue(payload["selected_variables"])
        self.assertEqual(payload["model"]["model_family"], "logistic_regression")
        self.assertIn("train", payload["validation_metrics"]["roles"])
        self.assertIn("train", payload["cutoff_analysis"]["cutoff_tables"])


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
