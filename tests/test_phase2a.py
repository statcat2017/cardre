"""Phase 2A acceptance tests covering the binning/WOE spine."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    table_logical_hash,
)
from cardre.executor import PlanExecutor, RoleAccessError
from cardre.nodes import (
    ApplyExclusionsNode,
    CalculateWoeIvNode,
    DefineModellingMetadataNode,
    DevelopmentSampleDefinitionNode,
    ExplicitMissingOutlierTreatmentNode,
    FineClassingNode,
    ImportGermanCreditNode,
    ManualBinningNode,
    ProfileDatasetNode,
    TechnicalManifestExportNode,
    VariableClusteringNode,
    VariableSelectionNode,
)
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore

from tests.test_phase1 import make_store, make_sample_german_credit_file, SAMPLE_GERMAN_CREDIT_LINES


# ======================================================================
# Helpers
# ======================================================================

def make_project_with_import(store: ProjectStore, tmp: Path) -> tuple[str, str]:
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
    executor.run_plan_version(store, pv_id)
    return project_id, plan_id


def make_full_german_credit_download(tmp: Path) -> Path:
    """Create a larger German Credit fixture with 10 rows for more meaningful testing."""
    lines = SAMPLE_GERMAN_CREDIT_LINES * 5
    p = tmp / "german_full.data"
    p.write_text("\n".join(lines))
    return p


# ======================================================================
# Workstream 1: Node-Level Input Contracts + Leakage Tests
# ======================================================================

class InputContractTests(unittest.TestCase):

    def test_fit_node_rejects_test_oot_datasets(self) -> None:
        from cardre.audit import ArtifactRef
        store, tmp = make_store()
        store.initialize()
        node = FineClassingNode()

        mock_train = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="train",
            path="mock", physical_hash="a", logical_hash="b",
        )
        mock_test = ArtifactRef(
            artifact_id="t2", artifact_type="dataset", role="test",
            path="mock", physical_hash="c", logical_hash="d",
        )
        mock_oot = ArtifactRef(
            artifact_id="t3", artifact_type="dataset", role="oot",
            path="mock", physical_hash="e", logical_hash="f",
        )

        with self.assertRaises(RoleAccessError):
            from cardre.executor import PlanExecutor
            executor = PlanExecutor(NodeRegistry.with_defaults())
            executor._validate_leakage_rules(node, [mock_test])

        with self.assertRaises(RoleAccessError):
            executor = PlanExecutor(NodeRegistry.with_defaults())
            executor._validate_leakage_rules(node, [mock_oot])

        try:
            executor = PlanExecutor(NodeRegistry.with_defaults())
            executor._validate_leakage_rules(node, [mock_train])
        except RoleAccessError:
            self.fail("Fit node should accept train dataset")

    def test_selection_node_rejects_test_tabular(self) -> None:
        from cardre.audit import ArtifactRef
        store, tmp = make_store()
        store.initialize()
        node = CalculateWoeIvNode()

        mock_test_dataset = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="test",
            path="mock", physical_hash="a", logical_hash="b",
        )
        mock_oot_dataset = ArtifactRef(
            artifact_id="t2", artifact_type="dataset", role="oot",
            path="mock", physical_hash="c", logical_hash="d",
        )

        executor = PlanExecutor(NodeRegistry.with_defaults())
        with self.assertRaises(RoleAccessError):
            executor._validate_leakage_rules(node, [mock_test_dataset])
        with self.assertRaises(RoleAccessError):
            executor._validate_leakage_rules(node, [mock_oot_dataset])

    def test_selection_node_accepts_report_artifacts(self) -> None:
        from cardre.audit import ArtifactRef
        store, tmp = make_store()
        store.initialize()
        node = CalculateWoeIvNode()

        mock_report = ArtifactRef(
            artifact_id="r1", artifact_type="report", role="report",
            path="mock", physical_hash="a", logical_hash="b",
        )

        executor = PlanExecutor(NodeRegistry.with_defaults())
        try:
            executor._validate_leakage_rules(node, [mock_report])
        except RoleAccessError:
            self.fail("Selection node should accept report artifacts")

    def test_transform_node_no_restrictions(self) -> None:
        from cardre.audit import ArtifactRef
        store, tmp = make_store()
        store.initialize()
        node = ProfileDatasetNode()

        mock_test_dataset = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="test",
            path="mock", physical_hash="a", logical_hash="b",
        )

        executor = PlanExecutor(NodeRegistry.with_defaults())
        try:
            executor._validate_leakage_rules(node, [mock_test_dataset])
        except RoleAccessError:
            self.fail("Transform node should accept any role")


# ======================================================================
# Workstream 2: Define Modelling Metadata
# ======================================================================

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
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test-data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
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

        self.assertEqual(len(output.artifacts), 1)
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
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test-data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
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
        from cardre.audit import physical_hash, relative_path
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({"age": [15, 18, 25, 30], "score": [1, 2, 3, 4]})
        import io
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

        self.assertEqual(len(output.artifacts), 1)
        self.assertEqual(output.artifacts[0].role, "input")


# ======================================================================
# Workstream 6: Fine Classing
# ======================================================================

class FineClassingTests(unittest.TestCase):

    def test_fine_classing_creates_bin_definitions(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "var2": ["a", "b", "a", "b", "a", "b"],
            "target": ["good", "good", "bad", "bad", "good", "bad"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        train_path = store.root / "datasets" / "test-train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(meta_artifact)

        params = {
            "max_bins": 20,
            "min_bin_fraction": 0.05,
            "missing_policy": "separate_bin",
            "max_categorical_levels": 50,
            "exclude_columns": [],
        }
        step_spec = StepSpec(
            step_id="fine-classing", node_type="cardre.fine_classing",
            node_version="1", category="fit",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["split", "define-metadata"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = FineClassingNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        artifact = output.artifacts[0]
        self.assertEqual(artifact.role, "definition")
        payload = json.loads(store.artifact_path(artifact).read_text())
        self.assertIn("variables", payload)
        self.assertGreater(len(payload["variables"]), 0)

    def test_fine_classing_max_bins_validation(self) -> None:
        store, tmp = make_store()
        store.initialize()
        from cardre.audit import ArtifactRef

        params = {"max_bins": 1, "min_bin_fraction": 0.05}
        mock_artifact = ArtifactRef(
            artifact_id="a1", artifact_type="dataset", role="train",
            path="nonexistent", physical_hash="a", logical_hash="b",
        )
        step_spec = StepSpec(
            step_id="fc", node_type="cardre.fine_classing",
            node_version="1", category="fit",
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
        node = FineClassingNode()
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Workstream 7: WOE/IV Calculation
# ======================================================================

class CalculateWoeIvTests(unittest.TestCase):

    def test_woe_iv_computes_deterministic_values(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "target": ["good", "bad", "good", "bad", "good", "bad"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        train_path = store.root / "datasets" / "test-train.parquet"
        train_path.parent.mkdir(parents=True, exist_ok=True)
        train_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(train_path, store.root),
            physical_hash=physical_hash(train_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        # Create a minimal bin definition
        bin_def = {
            "variables": [
                {
                    "variable": "var1",
                    "kind": "numeric",
                    "bins": [
                        {
                            "bin_id": "v1_bin_001",
                            "label": "Low",
                            "lower": 0, "upper": 3,
                            "lower_inclusive": False, "upper_inclusive": True,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 3, "good_count": 2, "bad_count": 1,
                        },
                        {
                            "bin_id": "v1_bin_002",
                            "label": "High",
                            "lower": 3, "upper": None,
                            "lower_inclusive": False, "upper_inclusive": True,
                            "categories": None, "is_missing_bin": False,
                            "row_count": 3, "good_count": 1, "bad_count": 2,
                        },
                    ],
                }
            ],
            "warnings": [],
        }

        bin_path = store.root / "artifacts" / "test-bins.json"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        from cardre.audit import physical_hash, relative_path
        bin_artifact = ArtifactRef(
            artifact_id="bin1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(bin_artifact)

        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(meta_artifact)

        params = {
            "zero_cell_policy": "block",
            "smoothing": None,
            "purpose": "initial",
        }
        step_spec = StepSpec(
            step_id="woe-iv", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["fine-classing"], branch_label="", position=1,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 4)

        woe_art = output.artifacts[0]
        iv_art = output.artifacts[1]
        summary_art = output.artifacts[2]
        evidence_art = output.artifacts[3]
        woe_df = pl.read_parquet(store.artifact_path(woe_art))
        iv_df = pl.read_parquet(store.artifact_path(iv_art))

        # Verify evidence v1 schema
        evidence = json.loads(store.artifact_path(evidence_art).read_text())
        self.assertEqual(evidence["schema_version"], "cardre.woe_iv_evidence.v1")
        self.assertIn("variables", evidence)
        self.assertIn("config", evidence)

        self.assertIn("woe", woe_df.columns)
        self.assertIn("iv_component", woe_df.columns)
        self.assertIn("iv", iv_df.columns)
        self.assertIn("variable", iv_df.columns)

    def test_deterministic_output(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "target": ["good", "bad", "good", "bad", "good"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path, table_logical_hash
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(parquet_path, store.root),
            physical_hash=physical_hash(parquet_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        bin_def = {
            "variables": [
                {
                    "variable": "var1",
                    "kind": "numeric",
                    "bins": [
                        {"bin_id": "v1_b1", "label": "Low", "lower": 0, "upper": 3,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 3, "good_count": 2, "bad_count": 1},
                        {"bin_id": "v1_b2", "label": "High", "lower": 3, "upper": None,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 2, "good_count": 1, "bad_count": 1},
                    ],
                }
            ],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "test-bins.json"
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="bin1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(bin_artifact)

        meta_params = {
            "target_column": "target",
            "good_values": ["good"], "bad_values": ["bad"],
        }
        meta_path = store.root / "artifacts" / "test-meta2.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(meta_artifact)

        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        out1 = node.run(ctx)

        ctx2 = ExecutionContext(
            store=store, run_id="r2", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, bin_artifact, meta_artifact],
            validated_params=params, runtime_metadata={},
        )
        out2 = node.run(ctx2)

        self.assertEqual(
            out1.artifacts[0].logical_hash,
            out2.artifacts[0].logical_hash,
            "WOE/IV should be deterministic",
        )

    def test_woe_iv_rejects_ambiguous_definition_artifacts(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "target": ["good", "bad", "good", "bad", "good"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path, table_logical_hash
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(parquet_path, store.root),
            physical_hash=physical_hash(parquet_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        bin_def = {
            "variables": [
                {
                    "variable": "var1", "kind": "numeric",
                    "bins": [{"bin_id": "v1_b1", "label": "All", "lower": 0, "upper": None,
                              "lower_inclusive": True, "upper_inclusive": True,
                              "categories": None, "is_missing_bin": False,
                              "row_count": 5, "good_count": 3, "bad_count": 2}],
                }
            ],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "test-bins.json"
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_artifact = ArtifactRef(
            artifact_id="bin1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact)

        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "test-meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_artifact = ArtifactRef(
            artifact_id="meta1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_artifact)

        # Add a second spurious bin artifact - should be rejected
        bin_def2 = {"variables": [{"variable": "other", "kind": "numeric", "bins": []}], "warnings": []}
        bin_path2 = store.root / "artifacts" / "test-bins2.json"
        bin_path2.write_text(json.dumps(bin_def2, sort_keys=True))
        bin_artifact2 = ArtifactRef(
            artifact_id="bin2", artifact_type="definition", role="definition",
            path=relative_path(bin_path2, store.root),
            physical_hash=physical_hash(bin_path2),
            logical_hash=json_logical_hash(bin_def2),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_artifact2)

        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
        step_spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[train_artifact, bin_artifact, meta_artifact, bin_artifact2],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        with self.assertRaises(ValueError):
            node.run(ctx)


# ======================================================================
# Workstream 8: Variable Clustering
# ======================================================================

class VariableClusteringTests(unittest.TestCase):

    def test_clustering_produces_clusters(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame({
            "num1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "num2": [2.0, 4.0, 6.0, 8.0, 10.0],
            "cat1": ["a", "b", "a", "b", "a"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        parquet_path = store.root / "datasets" / "test-train.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path, table_logical_hash
        train_artifact = ArtifactRef(
            artifact_id="train1", artifact_type="dataset", role="train",
            path=relative_path(parquet_path, store.root),
            physical_hash=physical_hash(parquet_path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(train_artifact)

        iv_df = pl.DataFrame({
            "variable": ["num1", "num2", "cat1"],
            "iv": [0.3, 0.25, 0.1],
            "bin_count": [2, 2, 1],
            "zero_cell_count": [0, 0, 0],
            "warning_count": [0, 0, 0],
        })
        iv_buf = io.BytesIO()
        iv_df.write_parquet(iv_buf)
        iv_path = store.root / "datasets" / "test-iv.parquet"
        iv_path.write_bytes(iv_buf.getvalue())
        iv_artifact = ArtifactRef(
            artifact_id="iv1", artifact_type="report", role="report",
            path=relative_path(iv_path, store.root),
            physical_hash=physical_hash(iv_path),
            logical_hash=table_logical_hash(iv_df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(iv_artifact)

        params = {"correlation_threshold": 0.7, "candidate_limit": 50}
        step_spec = StepSpec(
            step_id="clustering", node_type="cardre.variable_clustering",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[train_artifact, iv_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = VariableClusteringNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 1)
        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertIn("clusters", payload)
        self.assertGreater(len(payload["clusters"]), 0)


# ======================================================================
# Workstream 9: Variable Selection
# ======================================================================

class VariableSelectionTests(unittest.TestCase):

    def test_selection_includes_by_iv_threshold(self) -> None:
        store, tmp = make_store()
        store.initialize()

        iv_df = pl.DataFrame({
            "variable": ["v1", "v2", "v3", "v4"],
            "iv": [0.5, 0.03, 0.01, 0.4],
            "bin_count": [3, 3, 3, 3],
            "zero_cell_count": [0, 0, 0, 0],
            "warning_count": [0, 0, 0, 0],
        })
        import io
        buf = io.BytesIO()
        iv_df.write_parquet(buf)
        iv_path = store.root / "datasets" / "test-iv.parquet"
        iv_path.parent.mkdir(parents=True, exist_ok=True)
        iv_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path, table_logical_hash
        iv_artifact = ArtifactRef(
            artifact_id="iv1", artifact_type="report", role="report",
            path=relative_path(iv_path, store.root),
            physical_hash=physical_hash(iv_path),
            logical_hash=table_logical_hash(iv_df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(iv_artifact)

        clustering = {
            "correlation_threshold": 0.7,
            "candidate_limit": 50,
            "total_candidates": 4,
            "clusters": [
                {"cluster_id": "c1", "variables": ["v1"], "reason": "Singleton"},
                {"cluster_id": "c2", "variables": ["v2"], "reason": "Singleton"},
                {"cluster_id": "c3", "variables": ["v3"], "reason": "Singleton"},
                {"cluster_id": "c4", "variables": ["v4"], "reason": "Singleton"},
            ],
            "warnings": [],
        }
        clust_path = store.root / "artifacts" / "test-clust.json"
        clust_path.write_text(json.dumps(clustering, sort_keys=True))
        clust_artifact = ArtifactRef(
            artifact_id="clust1", artifact_type="report", role="report",
            path=relative_path(clust_path, store.root),
            physical_hash=physical_hash(clust_path),
            logical_hash=json_logical_hash(clustering),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(clust_artifact)

        params = {"min_iv": 0.02, "max_variables": 15, "manual_includes": [], "manual_excludes": []}
        step_spec = StepSpec(
            step_id="selection", node_type="cardre.variable_selection",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[iv_artifact, clust_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = VariableSelectionNode()
        output = node.run(ctx)

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        selected_vars = [s["variable"] for s in payload["selected"]]
        self.assertIn("v1", selected_vars)
        self.assertIn("v4", selected_vars)
        self.assertNotIn("v3", selected_vars)

    def test_every_selection_has_reason(self) -> None:
        store, tmp = make_store()
        store.initialize()

        iv_df = pl.DataFrame({
            "variable": ["v1", "v2"],
            "iv": [0.3, 0.02],
            "bin_count": [2, 2],
            "zero_cell_count": [0, 0],
            "warning_count": [0, 0],
        })
        import io
        buf = io.BytesIO()
        iv_df.write_parquet(buf)
        iv_path = store.root / "datasets" / "test-iv.parquet"
        iv_path.parent.mkdir(parents=True, exist_ok=True)
        iv_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path, table_logical_hash
        iv_artifact = ArtifactRef(
            artifact_id="iv1", artifact_type="report", role="report",
            path=relative_path(iv_path, store.root),
            physical_hash=physical_hash(iv_path),
            logical_hash=table_logical_hash(iv_df),
            media_type="application/vnd.apache.parquet",
            metadata={},
        )
        store.register_artifact(iv_artifact)

        clustering = {"clusters": [
            {"cluster_id": "c1", "variables": ["v1"], "reason": "Single"},
            {"cluster_id": "c2", "variables": ["v2"], "reason": "Single"},
        ], "warnings": []}
        clust_path = store.root / "artifacts" / "test-clust.json"
        clust_path.write_text(json.dumps(clustering, sort_keys=True))
        clust_artifact = ArtifactRef(
            artifact_id="clust2", artifact_type="report", role="report",
            path=relative_path(clust_path, store.root),
            physical_hash=physical_hash(clust_path),
            logical_hash=json_logical_hash(clustering),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(clust_artifact)

        params = {"min_iv": 0.02, "max_variables": 15}
        step_spec = StepSpec(
            step_id="sel", node_type="cardre.variable_selection",
            node_version="1", category="selection",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[iv_artifact, clust_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = VariableSelectionNode()
        output = node.run(ctx)

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        for entry in payload["selected"] + payload["rejected"]:
            self.assertIn("reason", entry)
            self.assertTrue(entry["reason"])


# ======================================================================
# Workstream 10: Manual Binning
# ======================================================================

class ManualBinningTests(unittest.TestCase):

    def test_manual_binning_merge_bins(self) -> None:
        store, tmp = make_store()
        store.initialize()

        bin_def = {
            "variables": [
                {
                    "variable": "duration_months",
                    "kind": "numeric",
                    "bins": [
                        {"bin_id": "dm_bin_001", "label": "Low", "lower": 0, "upper": 12,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 100, "good_count": 80, "bad_count": 20},
                        {"bin_id": "dm_bin_002", "label": "Mid", "lower": 12, "upper": 24,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 80, "good_count": 60, "bad_count": 20},
                        {"bin_id": "dm_bin_003", "label": "High", "lower": 24, "upper": None,
                         "lower_inclusive": False, "upper_inclusive": True,
                         "categories": None, "is_missing_bin": False,
                         "row_count": 50, "good_count": 30, "bad_count": 20},
                    ],
                }
            ],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "test-bins.json"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        from cardre.audit import physical_hash, relative_path
        bin_artifact = ArtifactRef(
            artifact_id="bin1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(bin_artifact)

        params = {
            "overrides": [
                {
                    "variable": "duration_months",
                    "action": "merge_bins",
                    "source_bin_ids": ["dm_bin_001", "dm_bin_002"],
                    "new_label": "Low-Mid",
                    "reason": "Merged sparse adjacent bins",
                }
            ]
        }
        step_spec = StepSpec(
            step_id="manual-binning", node_type="cardre.manual_binning",
            node_version="1", category="refinement",
            params=params,
            params_hash=json_logical_hash(params),
            parent_step_ids=["fine-classing"], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=step_spec,
            parent_run_steps=[], input_artifacts=[bin_artifact],
            validated_params=params, runtime_metadata={},
        )
        node = ManualBinningNode()
        output = node.run(ctx)

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        merged_vars = payload["variables"]
        self.assertEqual(len(merged_vars), 1)
        merged_bins = merged_vars[0]["bins"]
        self.assertEqual(len(merged_bins), 2)


# ======================================================================
# Workstream 11: Technical Manifest Stub
# ======================================================================

class TechnicalManifestTests(unittest.TestCase):

    def test_manifest_stub_created(self) -> None:
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

        from cardre.audit import ArtifactRef
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


# ======================================================================
# Workstream 12: End-to-End Scorecard Pathway Test
# ======================================================================

class ScorecardPathwayTests(unittest.TestCase):
    """End-to-end test running the Phase 2A pathway through the executor."""

    def test_full_phase2a_pathway_import_through_manifest(self) -> None:
        store, tmp = make_store()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "scorecard-test")
        source = make_full_german_credit_download(tmp)

        steps = [
            StepSpec(
                step_id="import", node_type="cardre.import_dataset",
                node_version="1", category="transform",
                params={"source_path": str(source)},
                params_hash=json_logical_hash({"source_path": str(source)}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="define-metadata", node_type="cardre.define_modelling_metadata",
                node_version="1", category="transform",
                params={
                    "target_column": "credit_risk_class",
                    "good_values": ["1"], "bad_values": ["2"],
                    "indeterminate_values": [], "population": "",
                    "product": "", "segment": "",
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
            ),
            StepSpec(
                step_id="apply-exclusions", node_type="cardre.apply_exclusions",
                node_version="1", category="transform",
                params={"rules": []},
                params_hash=json_logical_hash({"rules": []}),
                parent_step_ids=["import", "define-metadata"], branch_label="", position=2,
            ),
            StepSpec(
                step_id="profile", node_type="cardre.profile_dataset",
                node_version="1", category="transform",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=["apply-exclusions"], branch_label="", position=3,
            ),
            StepSpec(
                step_id="validate-target", node_type="cardre.validate_binary_target",
                node_version="1", category="transform",
                params={"target_column": "credit_risk_class"},
                params_hash=json_logical_hash({"target_column": "credit_risk_class"}),
                parent_step_ids=["apply-exclusions", "define-metadata"], branch_label="", position=4,
            ),
            StepSpec(
                step_id="sample-definition", node_type="cardre.development_sample_definition",
                node_version="1", category="transform",
                params={
                    "sample_method": "full_population",
                    "weight_column": None, "population_bad_rate": None,
                    "prior_probability_adjustment": None,
                },
                params_hash=json_logical_hash({
                    "sample_method": "full_population",
                    "weight_column": None, "population_bad_rate": None,
                    "prior_probability_adjustment": None,
                }),
                parent_step_ids=["apply-exclusions", "define-metadata"], branch_label="", position=5,
            ),
            StepSpec(
                step_id="split", node_type="cardre.split_train_test_oot",
                node_version="2", category="transform",
                params={
                    "strategy": "random_stratified",
                    "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                    "target_column": "credit_risk_class", "role_column": None,
                    "random_seed": 42,
                },
                params_hash=json_logical_hash({
                    "strategy": "random_stratified",
                    "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                    "target_column": "credit_risk_class", "role_column": None,
                    "random_seed": 42,
                }),
                parent_step_ids=["apply-exclusions", "sample-definition"], branch_label="", position=6,
            ),
            StepSpec(
                step_id="explicit-missing-outlier-treatment",
                node_type="cardre.explicit_missing_outlier_treatment",
                node_version="1", category="apply",
                params={"imputations": {}, "caps": {}, "floors": {}},
                params_hash=json_logical_hash({"imputations": {}, "caps": {}, "floors": {}}),
                parent_step_ids=["split"], branch_label="", position=7,
            ),
            StepSpec(
                step_id="fine-classing", node_type="cardre.fine_classing",
                node_version="1", category="fit",
                params={
                    "max_bins": 20, "min_bin_fraction": 0.05,
                    "missing_policy": "separate_bin",
                    "max_categorical_levels": 50, "exclude_columns": [],
                },
                params_hash=json_logical_hash({
                    "max_bins": 20, "min_bin_fraction": 0.05,
                    "missing_policy": "separate_bin",
                    "max_categorical_levels": 50, "exclude_columns": [],
                }),
                parent_step_ids=["explicit-missing-outlier-treatment", "define-metadata"],
                branch_label="", position=8,
            ),
            StepSpec(
                step_id="initial-woe-iv", node_type="cardre.calculate_woe_iv",
                node_version="1", category="selection",
                params={
                    "zero_cell_policy": "block", "smoothing": None, "purpose": "initial",
                },
                params_hash=json_logical_hash({
                    "zero_cell_policy": "block", "smoothing": None, "purpose": "initial",
                }),
                parent_step_ids=["explicit-missing-outlier-treatment", "fine-classing", "define-metadata"],
                branch_label="", position=9,
            ),
            StepSpec(
                step_id="variable-clustering", node_type="cardre.variable_clustering",
                node_version="1", category="selection",
                params={"correlation_threshold": 0.7, "candidate_limit": 50},
                params_hash=json_logical_hash({"correlation_threshold": 0.7, "candidate_limit": 50}),
                parent_step_ids=["explicit-missing-outlier-treatment", "initial-woe-iv"],
                branch_label="", position=10,
            ),
            StepSpec(
                step_id="variable-selection", node_type="cardre.variable_selection",
                node_version="1", category="selection",
                params={
                    "min_iv": 0.02, "max_variables": 15,
                    "manual_includes": [], "manual_excludes": [],
                },
                params_hash=json_logical_hash({
                    "min_iv": 0.02, "max_variables": 15,
                    "manual_includes": [], "manual_excludes": [],
                }),
                parent_step_ids=["initial-woe-iv", "variable-clustering"],
                branch_label="", position=11,
            ),
            StepSpec(
                step_id="manual-binning", node_type="cardre.manual_binning",
                node_version="1", category="refinement",
                params={"overrides": []},
                params_hash=json_logical_hash({"overrides": []}),
                parent_step_ids=["fine-classing", "variable-selection"],
                branch_label="", position=12,
            ),
            StepSpec(
                step_id="final-woe-iv", node_type="cardre.calculate_woe_iv",
                node_version="1", category="selection",
                params={
                    "zero_cell_policy": "block",
                    "smoothing": {
                        "method": "additive",
                        "alpha": 0.5,
                        "rationale": "Small sample test fixture with sparse bins",
                    },
                    "purpose": "final",
                },
                params_hash=json_logical_hash({
                    "zero_cell_policy": "block",
                    "smoothing": {
                        "method": "additive",
                        "alpha": 0.5,
                        "rationale": "Small sample test fixture with sparse bins",
                    },
                    "purpose": "final",
                }),
                parent_step_ids=["explicit-missing-outlier-treatment", "manual-binning", "define-metadata"],
                branch_label="", position=13,
            ),
            StepSpec(
                step_id="technical-manifest-stub",
                node_type="cardre.technical_manifest_export",
                node_version="1", category="transform",
                params={},
                params_hash=json_logical_hash({}),
                parent_step_ids=[
                    "define-metadata", "sample-definition", "split",
                    "explicit-missing-outlier-treatment", "fine-classing",
                    "variable-selection", "manual-binning", "final-woe-iv",
                ],
                branch_label="", position=14,
            ),
        ]

        pv_id = store.create_plan_version(plan_id, steps)
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        run_id = executor.run_plan_version(store, pv_id)

        run = store.get_run(run_id)
        self.assertEqual(
            run["status"], "succeeded",
            f"Phase 2A pathway should succeed. Status: {run['status']}",
        )

        run_steps = store.get_run_steps(run_id)
        run_steps_by_id = {rs.step_id: rs for rs in run_steps}

        # Verify all steps succeeded
        for step in steps:
            rs = run_steps_by_id.get(step.step_id)
            self.assertIsNotNone(rs, f"No run step for {step.step_id}")
            self.assertEqual(
                rs.status, "succeeded",
                f"Step {step.step_id} failed: {rs.errors}",
            )

        # Verify key artifacts exist
        artifact_types_by_step = {
            "define-metadata": "definition",
            "fine-classing": "definition",
            "variable-selection": "definition",
            "manual-binning": "definition",
            "technical-manifest-stub": "manifest",
        }
        for step_id, expected_type in artifact_types_by_step.items():
            rs = run_steps_by_id[step_id]
            for aid in rs.output_artifact_ids:
                art = store.get_artifact(aid)
                if art and art.artifact_type == expected_type:
                    break
            else:
                self.fail(f"No {expected_type} artifact found for step {step_id}")

        # Verify initial and final WOE/IV produce report artifacts
        for woe_step in ("initial-woe-iv", "final-woe-iv"):
            rs = run_steps_by_id[woe_step]
            report_found = any(
                store.get_artifact(aid) and store.get_artifact(aid).artifact_type == "report"
                for aid in rs.output_artifact_ids
            )
            self.assertTrue(report_found, f"No report artifact for {woe_step}")


# ======================================================================
# Blocker Verification Tests (PR #4 review findings)
# ======================================================================

class BlockerVerificationTests(unittest.TestCase):
    """Direct tests locking down the PR #4 review blocker fixes."""

    def test_blank_target_column_fails(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({"col1": [1, 2]})
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "test.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
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

    def test_final_woe_zero_cell_block_fails_without_smoothing(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "var1": [1.0, 2.0, 3.0],
            "target": ["good", "good", "bad"],
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "train.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
        train = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="train",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(train)

        bin_def = {
            "variables": [{
                "variable": "var1", "kind": "numeric",
                "bins": [
                    {"bin_id": "v1_b1", "label": "A", "lower": 0, "upper": 2,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 2, "good_count": 2, "bad_count": 0},
                    {"bin_id": "v1_b2", "label": "B", "lower": 2, "upper": None,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 1, "good_count": 0, "bad_count": 1},
                ],
            }],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "bins.json"
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        bin_art = ArtifactRef(
            artifact_id="b1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_art)

        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_art = ArtifactRef(
            artifact_id="m1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_art)

        params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "final"}
        spec = StepSpec(
            step_id="woe", node_type="cardre.calculate_woe_iv",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train, bin_art, meta_art],
            validated_params=params, runtime_metadata={},
        )
        node = CalculateWoeIvNode()
        with self.assertRaises(ValueError):
            node.run(ctx)

    def test_non_adjacent_numeric_merge_fails(self) -> None:
        store, tmp = make_store()
        store.initialize()
        bin_def = {
            "variables": [{
                "variable": "x", "kind": "numeric",
                "bins": [
                    {"bin_id": "b1", "label": "A", "lower": 0, "upper": 10,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 100, "good_count": 80, "bad_count": 20},
                    {"bin_id": "b2", "label": "B", "lower": 10, "upper": 20,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 100, "good_count": 80, "bad_count": 20},
                    {"bin_id": "b3", "label": "C", "lower": 20, "upper": 30,
                     "lower_inclusive": False, "upper_inclusive": True,
                     "categories": None, "is_missing_bin": False,
                     "row_count": 100, "good_count": 80, "bad_count": 20},
                ],
            }],
            "warnings": [],
        }
        bin_path = store.root / "artifacts" / "bins.json"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(json.dumps(bin_def, sort_keys=True))
        from cardre.audit import physical_hash, relative_path
        bin_art = ArtifactRef(
            artifact_id="b1", artifact_type="definition", role="definition",
            path=relative_path(bin_path, store.root),
            physical_hash=physical_hash(bin_path),
            logical_hash=json_logical_hash(bin_def),
            media_type="application/json", metadata={},
        )
        store.register_artifact(bin_art)

        params = {
            "overrides": [{
                "variable": "x",
                "action": "merge_bins",
                "source_bin_ids": ["b1", "b3"],
                "new_label": "Non-adjacent",
                "reason": "Testing adjacency enforcement",
            }]
        }
        spec = StepSpec(
            step_id="mb", node_type="cardre.manual_binning",
            node_version="1", category="refinement",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[bin_art],
            validated_params=params, runtime_metadata={},
        )
        node = ManualBinningNode()
        with self.assertRaises(ValueError):
            node.run(ctx)

    def test_high_cardinality_creates_other_bin(self) -> None:
        store, tmp = make_store()
        store.initialize()
        df = pl.DataFrame({
            "cat_var": [f"level_{i}" for i in range(60)],
            "target": ["good"] * 30 + ["bad"] * 30,
        })
        import io
        buf = io.BytesIO()
        df.write_parquet(buf)
        path = store.root / "datasets" / "train.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
        train = ArtifactRef(
            artifact_id="t1", artifact_type="dataset", role="train",
            path=relative_path(path, store.root),
            physical_hash=physical_hash(path),
            logical_hash=table_logical_hash(df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(train)

        meta_params = {"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]}
        meta_path = store.root / "artifacts" / "meta.json"
        meta_path.write_text(json.dumps(meta_params, sort_keys=True))
        meta_art = ArtifactRef(
            artifact_id="m1", artifact_type="definition", role="definition",
            path=relative_path(meta_path, store.root),
            physical_hash=physical_hash(meta_path),
            logical_hash=json_logical_hash(meta_params),
            media_type="application/json", metadata={},
        )
        store.register_artifact(meta_art)

        params = {
            "max_bins": 20, "min_bin_fraction": 0.01,
            "missing_policy": "separate_bin",
            "max_categorical_levels": 10,
            "exclude_columns": [],
        }
        spec = StepSpec(
            step_id="fc", node_type="cardre.fine_classing",
            node_version="1", category="fit",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[train, meta_art],
            validated_params=params, runtime_metadata={},
        )
        node = FineClassingNode()
        output = node.run(ctx)

        payload = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        cat_var = next(v for v in payload["variables"] if v["variable"] == "cat_var")
        bin_labels = [b["label"] for b in cat_var["bins"]]
        self.assertIn("Other", bin_labels, "High-cardinality categorical should create an 'Other' bin")

    def test_variable_selection_requires_reasons_for_dict_entries(self) -> None:
        store, tmp = make_store()
        store.initialize()
        iv_df = pl.DataFrame({
            "variable": ["v1"], "iv": [0.3], "bin_count": [2],
            "zero_cell_count": [0], "warning_count": [0],
        })
        import io
        buf = io.BytesIO()
        iv_df.write_parquet(buf)
        iv_path = store.root / "datasets" / "iv.parquet"
        iv_path.parent.mkdir(parents=True, exist_ok=True)
        iv_path.write_bytes(buf.getvalue())
        from cardre.audit import physical_hash, relative_path
        iv_art = ArtifactRef(
            artifact_id="iv1", artifact_type="report", role="report",
            path=relative_path(iv_path, store.root),
            physical_hash=physical_hash(iv_path),
            logical_hash=table_logical_hash(iv_df),
            media_type="application/vnd.apache.parquet", metadata={},
        )
        store.register_artifact(iv_art)

        clustering = {"clusters": [{"cluster_id": "c1", "variables": ["v1"], "reason": "Single"}], "warnings": []}
        clust_path = store.root / "artifacts" / "clust.json"
        clust_path.write_text(json.dumps(clustering, sort_keys=True))
        clust_art = ArtifactRef(
            artifact_id="cl1", artifact_type="report", role="report",
            path=relative_path(clust_path, store.root),
            physical_hash=physical_hash(clust_path),
            logical_hash=json_logical_hash(clustering),
            media_type="application/json", metadata={},
        )
        store.register_artifact(clust_art)

        params = {
            "min_iv": 0.02, "max_variables": 15,
            "manual_includes": ["v1"],
            "manual_excludes": [],
        }
        spec = StepSpec(
            step_id="sel", node_type="cardre.variable_selection",
            node_version="1", category="selection",
            params=params, params_hash=json_logical_hash(params),
            parent_step_ids=[], branch_label="", position=0,
        )
        ctx = ExecutionContext(
            store=store, run_id="r1", plan_version_id="pv1",
            step_spec=spec, parent_run_steps=[],
            input_artifacts=[iv_art, clust_art],
            validated_params=params, runtime_metadata={},
        )
        node = VariableSelectionNode()
        with self.assertRaises(ValueError):
            node.run(ctx)


if __name__ == "__main__":
    unittest.main()
