"""Tests for Phase 0 (cutoff label fix) and Phase 1 (generic model contract)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    StepSpec,
    json_logical_hash,
)
from cardre.modeling.schema import (
    MODEL_ARTIFACT_SCHEMA_VERSION,
    FeatureContract,
    InterpretabilityMetadata,
    ModelArtifactV1,
    PredictionContract,
    TrainingMetadata,
    estimate_probability_column_index,
    validate_model_artifact,
)
from cardre.modeling.serialization import (
    read_estimator_artifact,
    write_estimator_artifact,
)
from cardre.nodes.validate import CutoffAnalysisNode, ValidationMetricsNode
from cardre.store import ProjectStore


# ======================================================================
# Helpers
# ======================================================================

def make_store() -> tuple[ProjectStore, Path]:
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store, tmp


def make_dataset_artifact(store: ProjectStore, df: pl.DataFrame, role: str = "train"):
    from cardre.artifacts import write_parquet_artifact
    return write_parquet_artifact(
        store, artifact_type="dataset", role=role,
        stem=f"test-{role}", frame=df, metadata={},
    )


def make_definition_artifact(store: ProjectStore, target_column: str, good_values: list, bad_values: list):
    from cardre.artifacts import write_json_artifact
    return write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="test-definition",
        payload={
            "target_column": target_column,
            "good_values": good_values,
            "bad_values": bad_values,
        },
        metadata={},
    )


# ======================================================================
# Phase 0: Cutoff Analysis Label Fix
# ======================================================================

class CutoffAnalysisLabelTests(unittest.TestCase):

    def test_cutoff_uses_actual_target_not_predicted_probability(self) -> None:
        """Verify cutoff analysis derives y_bin from target column, not predicted_bad_probability."""
        store, tmp = make_store()

        # Dataset where predicted_bad_probability contradicts actual target
        # Row 0: target=good, predicted as bad (model error)
        # Row 1: target=bad, predicted as good (model error)
        # Row 2: target=bad, predicted as bad (correct)
        # Row 3: target=good, predicted as good (correct)
        df = pl.DataFrame({
            "score": [100.0, 200.0, 300.0, 400.0],
            "predicted_bad_probability": [0.9, 0.1, 0.8, 0.2],
            "target": ["good", "bad", "bad", "good"],
        })

        data_art = make_dataset_artifact(store, df, "train")
        def_art = make_definition_artifact(store, "target", ["good"], ["bad"])

        step_spec = StepSpec(
            step_id="cutoff-1",
            node_type="cardre.cutoff_analysis",
            node_version="1",
            category="apply",
            params={"band_count": 2},
            params_hash=json_logical_hash({"band_count": 2}),
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
            input_artifacts=[data_art, def_art],
            validated_params={"band_count": 2},
            runtime_metadata={},
        )

        node = CutoffAnalysisNode()
        output = node.run(ctx)

        report = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        train_report = report["train"]

        # Actual bad count = 2 (rows 1 and 2 have target=bad)
        self.assertEqual(train_report["overall_bad_rate"], 0.5)

        # Bands should use actual target labels, not predicted_bad_probability
        bands = train_report["bands"]
        self.assertEqual(len(bands), 2)

        # Band 1 (score <= 200): rows 0,1 -> 1 bad (row 1)
        # Band 2 (score > 200): rows 2,3 -> 1 bad (row 2)
        bad_counts = [b["bad_count"] for b in bands]
        self.assertEqual(sum(bad_counts), 2)

    def test_cutoff_warns_when_target_column_missing(self) -> None:
        """Verify cutoff analysis warns when target column is not in dataset."""
        store, tmp = make_store()

        df = pl.DataFrame({
            "score": [100.0, 200.0],
            "predicted_bad_probability": [0.9, 0.1],
        })

        data_art = make_dataset_artifact(store, df, "train")
        def_art = make_definition_artifact(store, "missing_target", ["good"], ["bad"])

        step_spec = StepSpec(
            step_id="cutoff-2",
            node_type="cardre.cutoff_analysis",
            node_version="1",
            category="apply",
            params={"band_count": 2},
            params_hash=json_logical_hash({"band_count": 2}),
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
            input_artifacts=[data_art, def_art],
            validated_params={"band_count": 2},
            runtime_metadata={},
        )

        node = CutoffAnalysisNode()
        output = node.run(ctx)

        report = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertIn("warnings", report)
        warning_codes = [w["code"] for w in report["warnings"]]
        self.assertIn("MISSING_TARGET_COLUMN", warning_codes)

    def test_cutoff_warns_when_no_good_bad_values(self) -> None:
        """Verify cutoff analysis warns when definition has no good/bad values."""
        store, tmp = make_store()

        df = pl.DataFrame({
            "score": [100.0, 200.0],
            "predicted_bad_probability": [0.9, 0.1],
            "target": ["a", "b"],
        })

        data_art = make_dataset_artifact(store, df, "train")
        def_art = make_definition_artifact(store, "target", [], [])

        step_spec = StepSpec(
            step_id="cutoff-3",
            node_type="cardre.cutoff_analysis",
            node_version="1",
            category="apply",
            params={"band_count": 2},
            params_hash=json_logical_hash({"band_count": 2}),
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
            input_artifacts=[data_art, def_art],
            validated_params={"band_count": 2},
            runtime_metadata={},
        )

        node = CutoffAnalysisNode()
        output = node.run(ctx)

        report = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertIn("warnings", report)
        warning_codes = [w["code"] for w in report["warnings"]]
        self.assertIn("MISSING_TARGET_METADATA", warning_codes)

    def test_cutoff_class_inversion_detection(self) -> None:
        """Verify that cutoff uses actual labels even when class order would invert results."""
        store, tmp = make_store()

        # Simulate: bad encoded as 0 (unusual), good as 1
        # Model predicts high probability for bad (0), low for good (1)
        df = pl.DataFrame({
            "score": [100.0, 200.0, 300.0, 400.0],
            "predicted_bad_probability": [0.1, 0.2, 0.8, 0.9],
            "target": ["0", "0", "1", "1"],  # 0=bad, 1=good
        })

        data_art = make_dataset_artifact(store, df, "train")
        def_art = make_definition_artifact(store, "target", ["1"], ["0"])

        step_spec = StepSpec(
            step_id="cutoff-4",
            node_type="cardre.cutoff_analysis",
            node_version="1",
            category="apply",
            params={"band_count": 2},
            params_hash=json_logical_hash({"band_count": 2}),
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
            input_artifacts=[data_art, def_art],
            validated_params={"band_count": 2},
            runtime_metadata={},
        )

        node = CutoffAnalysisNode()
        output = node.run(ctx)

        report = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        train_report = report["train"]

        # Actual bad count = 2 (rows 0,1 have target="0" which is bad)
        self.assertEqual(train_report["overall_bad_rate"], 0.5)


# ======================================================================
# Phase 1: Model Artifact Schema
# ======================================================================

class ModelArtifactSchemaTests(unittest.TestCase):

    def test_model_artifact_v1_roundtrip(self) -> None:
        """Verify ModelArtifactV1 serializes and deserializes correctly."""
        artifact = ModelArtifactV1(
            schema_version=MODEL_ARTIFACT_SCHEMA_VERSION,
            model_family="logistic_regression",
            target_column="risk",
            target_event_value="bad",
            class_mapping={"0": "good", "1": "bad"},
            probability_column_index=1,
            feature_contract=FeatureContract(
                features=["feat_a", "feat_b"],
                transformation_strategy="woe",
            ),
            training=TrainingMetadata(row_count=1000),
            model_payload={"intercept": 0.5, "coefficients": {"feat_a": 0.3}},
        )

        d = artifact.to_dict()
        restored = ModelArtifactV1.from_dict(d)

        self.assertEqual(restored.schema_version, MODEL_ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(restored.model_family, "logistic_regression")
        self.assertEqual(restored.target_column, "risk")
        self.assertEqual(restored.target_event_value, "bad")
        self.assertEqual(restored.probability_column_index, 1)
        self.assertEqual(restored.feature_contract.features, ["feat_a", "feat_b"])
        self.assertEqual(restored.training.row_count, 1000)
        self.assertEqual(restored.model_payload["intercept"], 0.5)

    def test_validate_model_artifact_valid(self) -> None:
        """Verify validate_model_artifact accepts a valid artifact."""
        data = {
            "schema_version": MODEL_ARTIFACT_SCHEMA_VERSION,
            "model_family": "logistic_regression",
            "target_column": "risk",
            "target_event_value": "bad",
            "class_mapping": {"0": "good", "1": "bad"},
            "probability_column_index": 1,
            "feature_contract": {"features": ["a", "b"]},
            "training": {"row_count": 100},
        }
        errors = validate_model_artifact(data)
        self.assertEqual(errors, [])

    def test_validate_model_artifact_missing_fields(self) -> None:
        """Verify validate_model_artifact rejects artifacts with missing fields."""
        data = {"schema_version": MODEL_ARTIFACT_SCHEMA_VERSION}
        errors = validate_model_artifact(data)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("model_family" in e for e in errors))

    def test_validate_model_artifact_wrong_schema_version(self) -> None:
        """Verify validate_model_artifact rejects wrong schema version."""
        data = {
            "schema_version": "wrong.version",
            "model_family": "logistic_regression",
            "target_column": "risk",
            "target_event_value": "bad",
            "class_mapping": {"0": "good", "1": "bad"},
            "probability_column_index": 1,
            "feature_contract": {"features": ["a"]},
            "training": {"row_count": 100},
        }
        errors = validate_model_artifact(data)
        self.assertTrue(any("schema_version" in e for e in errors))

    def test_estimate_probability_column_index(self) -> None:
        """Verify probability column index estimation from class mapping."""
        self.assertEqual(
            estimate_probability_column_index({"0": "good", "1": "bad"}, "bad"),
            1,
        )
        self.assertEqual(
            estimate_probability_column_index({"0": "bad", "1": "good"}, "bad"),
            0,
        )
        self.assertEqual(
            estimate_probability_column_index({}, "bad"),
            1,
        )

    def test_feature_contract_roundtrip(self) -> None:
        fc = FeatureContract(
            features=["x", "y"],
            transformation_strategy="encoded_raw",
            missing_policy="fill_zero",
        )
        d = fc.to_dict()
        restored = FeatureContract.from_dict(d)
        self.assertEqual(restored.features, ["x", "y"])
        self.assertEqual(restored.transformation_strategy, "encoded_raw")
        self.assertEqual(restored.missing_policy, "fill_zero")

    def test_prediction_contract_defaults(self) -> None:
        pc = PredictionContract()
        self.assertEqual(pc.probability_semantics, "p(bad)")
        self.assertEqual(pc.score_direction, "higher_is_lower_risk")

    def test_training_metadata_converged(self) -> None:
        tm = TrainingMetadata(row_count=500, converged=True, iterations=42)
        d = tm.to_dict()
        self.assertTrue(d["converged"])
        self.assertEqual(d["iterations"], 42)


# ======================================================================
# Phase 1: Secure Estimator Serialization
# ======================================================================

class EstimatorSerializationTests(unittest.TestCase):

    def test_write_and_read_estimator_artifact(self) -> None:
        """Verify round-trip write/read of estimator artifact."""
        store, tmp = make_store()

        data = b"fake estimator bytes"
        artifact = write_estimator_artifact(
            store,
            estimator_bytes=data,
            estimator_format="pickle",
            stem="test-estimator",
            creating_run_id="run-1",
            creating_run_step_id="step-1",
        )

        self.assertEqual(artifact.artifact_type, "estimator")
        self.assertEqual(artifact.metadata["estimator_format"], "pickle")
        self.assertEqual(artifact.metadata["creating_run_id"], "run-1")

        read_data = read_estimator_artifact(store, artifact)
        self.assertEqual(read_data, data)

    def test_read_estimator_verifies_hash(self) -> None:
        """Verify read_estimator_artifact checks hash mismatch."""
        store, tmp = make_store()

        data = b"test data"
        artifact = write_estimator_artifact(
            store,
            estimator_bytes=data,
            estimator_format="pickle",
            stem="test-hash",
            creating_run_id="run-1",
        )

        with self.assertRaises(ValueError) as ctx:
            read_estimator_artifact(store, artifact, expected_logical_hash="wrong_hash")
        self.assertIn("hash mismatch", str(ctx.exception))

    def test_read_estimator_rejects_untrusted(self) -> None:
        """Verify read_estimator_artifact rejects artifacts without creating_run_id."""
        store, tmp = make_store()

        data = b"untrusted data"
        artifact = write_estimator_artifact(
            store,
            estimator_bytes=data,
            estimator_format="pickle",
            stem="test-untrusted",
            creating_run_id="",
        )

        with self.assertRaises(ValueError) as ctx:
            read_estimator_artifact(store, artifact, trusted_only=True)
        self.assertIn("untrusted", str(ctx.exception))

    def test_read_estimator_allows_untrusted_when_flagged(self) -> None:
        """Verify read_estimator_artifact allows untrusted when trusted_only=False."""
        store, tmp = make_store()

        data = b"untrusted data"
        artifact = write_estimator_artifact(
            store,
            estimator_bytes=data,
            estimator_format="pickle",
            stem="test-override",
            creating_run_id="",
        )

        read_data = read_estimator_artifact(store, artifact, trusted_only=False)
        self.assertEqual(read_data, data)


if __name__ == "__main__":
    unittest.main()
