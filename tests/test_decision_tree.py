"""Tests for Phase 2: Decision Tree Challenger."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.modeling.schema import validate_model_artifact
from cardre.nodes.ml_models import DecisionTreeNode
from cardre.nodes.validate import ApplyModelNode, ValidationMetricsNode
from cardre.store import ProjectStore


# ======================================================================
# Helpers
# ======================================================================

def make_store() -> tuple[ProjectStore, Path]:
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store, tmp


def make_numeric_dataset(
    store: ProjectStore,
    n_rows: int = 100,
    seed: int = 42,
) -> tuple:
    """Create a synthetic numeric dataset with known structure."""
    rng = np.random.RandomState(seed)

    feat_a = rng.randn(n_rows) * 10 + 50
    feat_b = rng.randn(n_rows) * 5 + 20
    feat_c = rng.randn(n_rows) * 2 + 10

    # Target: bad when feat_a > 55 and feat_b > 22
    target = []
    for i in range(n_rows):
        if feat_a[i] > 55 and feat_b[i] > 22:
            target.append("bad")
        else:
            target.append("good")

    df = pl.DataFrame({
        "feat_a": feat_a,
        "feat_b": feat_b,
        "feat_c": feat_c,
        "target": target,
    })

    from cardre.artifacts import write_parquet_artifact, write_json_artifact
    data_art = write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="synthetic-train", frame=df, metadata={},
    )
    def_art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem="synthetic-definition",
        payload={
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
        },
        metadata={},
    )
    return data_art, def_art, df


def make_oot_dataset(
    store: ProjectStore,
    df: pl.DataFrame,
    seed: int = 99,
) -> tuple:
    """Create an OOT dataset from the training data with slight noise."""
    rng = np.random.RandomState(seed)
    n_rows = df.height

    feat_a = df["feat_a"].to_numpy() + rng.randn(n_rows) * 2
    feat_b = df["feat_b"].to_numpy() + rng.randn(n_rows) * 1
    feat_c = df["feat_c"].to_numpy() + rng.randn(n_rows) * 0.5

    target = []
    for i in range(n_rows):
        if feat_a[i] > 55 and feat_b[i] > 22:
            target.append("bad")
        else:
            target.append("good")

    oot_df = pl.DataFrame({
        "feat_a": feat_a,
        "feat_b": feat_b,
        "feat_c": feat_c,
        "target": target,
    })

    from cardre.artifacts import write_parquet_artifact
    oot_art = write_parquet_artifact(
        store, artifact_type="dataset", role="oot",
        stem="synthetic-oot", frame=oot_df, metadata={},
    )
    return oot_art, oot_df


def make_dt_context(
    store: ProjectStore,
    data_art,
    def_art,
    *,
    params: dict | None = None,
    run_id: str = "test-run",
    step_id: str = "dt-fit",
) -> ExecutionContext:
    if params is None:
        params = {
            "feature_strategy": "raw_numeric",
            "max_depth": 3,
            "min_samples_leaf": 5,
            "random_seed": 42,
        }
    step_spec = StepSpec(
        step_id=step_id,
        node_type="cardre.decision_tree_classifier",
        node_version="1",
        category="fit",
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=[],
        branch_label="",
        position=0,
    )
    return ExecutionContext(
        store=store,
        run_id=run_id,
        plan_version_id="test-pv",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=[data_art, def_art],
        validated_params=params,
        runtime_metadata={},
    )


# ======================================================================
# Parameter Validation
# ======================================================================

class DecisionTreeParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "max_depth": 3,
            "min_samples_leaf": 5,
            "random_seed": 42,
        })
        self.assertEqual(errors, [])

    def test_invalid_feature_strategy(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({"feature_strategy": "invalid"})
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("feature_strategy" in e for e in errors))

    def test_max_depth_zero(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({"feature_strategy": "raw_numeric", "max_depth": 0})
        self.assertGreater(len(errors), 0)

    def test_min_samples_leaf_zero(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({"feature_strategy": "raw_numeric", "min_samples_leaf": 0})
        self.assertGreater(len(errors), 0)

    def test_valid_balanced_class_weight(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": "balanced",
        })
        self.assertEqual(errors, [])

    def test_valid_dict_class_weight(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": {0: 1, 1: 5},
        })
        self.assertEqual(errors, [])

    def test_invalid_class_weight(self) -> None:
        node = DecisionTreeNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": "invalid",
        })
        self.assertGreater(len(errors), 0)


# ======================================================================
# Core Fitting
# ======================================================================

class DecisionTreeFitTests(unittest.TestCase):

    def test_fit_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        model_art = output.artifacts[0]
        self.assertEqual(model_art.artifact_type, "model")
        self.assertEqual(model_art.role, "model")

        model = json.loads(store.artifact_path(model_art).read_text())
        self.assertEqual(model["schema_version"], "cardre.model_artifact.v1")
        self.assertEqual(model["model_family"], "decision_tree")

    def test_model_artifact_passes_validation(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        errors = validate_model_artifact(model)
        self.assertEqual(errors, [])

    def test_fit_produces_estimator_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        estimator_art = output.artifacts[1]
        self.assertEqual(estimator_art.artifact_type, "estimator")
        self.assertTrue(
            store.artifact_path(estimator_art).exists(),
            "Estimator artifact file must exist on disk",
        )

    def test_fit_exports_tree_rules(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        rules = model["model_payload"]["tree_rules"]
        self.assertIsInstance(rules, list)
        self.assertGreater(len(rules), 0)

        for rule in rules:
            self.assertIn("rule_id", rule)
            self.assertIn("prediction", rule)
            self.assertIn("probability", rule)
            self.assertIn("conditions", rule)
            self.assertIn("sample_count", rule)

    def test_fit_records_tree_depth_and_leaf_count(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertIn("tree_depth", model["model_payload"])
        self.assertIn("leaf_count", model["model_payload"])
        self.assertGreater(model["model_payload"]["tree_depth"], 0)
        self.assertGreater(model["model_payload"]["leaf_count"], 0)

    def test_fit_records_feature_importance(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        importance = model["model_payload"]["feature_importance"]
        self.assertIsInstance(importance, dict)
        self.assertGreater(len(importance), 0)

    def test_fit_records_interpretability_metadata(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        interp = model["interpretability"]
        self.assertEqual(interp["explanation_type"], "tree_rules")
        self.assertEqual(interp["explanation_level"], "native_interpretable")
        self.assertTrue(interp["native_importance_available"])

    def test_fit_records_estimator_reference(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        ref = model["estimator_reference"]
        self.assertTrue(ref["artifact_id"])
        self.assertTrue(ref["logical_hash"])
        self.assertTrue(ref["physical_hash"])
        self.assertEqual(ref["estimator_format"], "joblib")
        self.assertTrue(ref["trusted_load_required"])

    def test_fit_records_class_mapping(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art)

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertIn("class_mapping", model)
        self.assertIn("target_event_value", model)
        self.assertEqual(model["target_event_value"], "bad")

    def test_fit_records_feature_strategy(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "max_depth": 3,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["feature_strategy"], "raw_numeric")


# ======================================================================
# Error Handling
# ======================================================================

class DecisionTreeErrorTests(unittest.TestCase):

    def test_rejects_non_numeric_columns(self) -> None:
        store, tmp = make_store()

        df = pl.DataFrame({
            "feat_a": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "category": ["a", "b", "c", "d", "e"] * 20,
            "target": ["good", "bad", "good", "bad", "good"] * 20,
        })

        from cardre.artifacts import write_parquet_artifact, write_json_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="cat-train", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="cat-def",
            payload={
                "target_column": "target",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={},
        )

        ctx = make_dt_context(store, data_art, def_art)
        node = DecisionTreeNode()
        with self.assertRaises(ValueError) as ctx_mgr:
            node.run(ctx)
        self.assertIn("Non-numeric", str(ctx_mgr.exception))

    def test_rejects_missing_target_column(self) -> None:
        store, tmp = make_store()

        df = pl.DataFrame({
            "feat_a": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "feat_b": [5.0, 4.0, 3.0, 2.0, 1.0] * 20,
        })

        from cardre.artifacts import write_parquet_artifact, write_json_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="no-target-train", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="no-target-def",
            payload={
                "target_column": "missing_target",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={},
        )

        ctx = make_dt_context(store, data_art, def_art)
        node = DecisionTreeNode()
        with self.assertRaises(ValueError):
            node.run(ctx)

    def test_rejects_single_class(self) -> None:
        store, tmp = make_store()

        df = pl.DataFrame({
            "feat_a": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "target": ["good"] * 100,
        })

        from cardre.artifacts import write_parquet_artifact, write_json_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="single-class-train", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="single-class-def",
            payload={
                "target_column": "target",
                "good_values": ["good"],
                "bad_values": ["bad"],
            },
            metadata={},
        )

        ctx = make_dt_context(store, data_art, def_art)
        node = DecisionTreeNode()
        with self.assertRaises(ValueError) as ctx_mgr:
            node.run(ctx)
        self.assertIn("bad-class", str(ctx_mgr.exception))

    def test_include_columns_works(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "include_columns": ["feat_a", "feat_b"],
            "max_depth": 2,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["features"], ["feat_a", "feat_b"])

    def test_exclude_columns_works(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "exclude_columns": ["feat_c"],
            "max_depth": 2,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertNotIn("feat_c", model["features"])

    def test_max_depth_controls_tree(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store, n_rows=200)

        ctx_shallow = make_dt_context(store, data_art, def_art, params={
            "feature_strategy": "raw_numeric",
            "max_depth": 2,
            "random_seed": 42,
        })

        node = DecisionTreeNode()
        output_shallow = node.run(ctx_shallow)

        model_shallow = json.loads(store.artifact_path(output_shallow.artifacts[0]).read_text())
        self.assertLessEqual(model_shallow["model_payload"]["tree_depth"], 2)


# ======================================================================
# Integration with ApplyModelNode
# ======================================================================

class DecisionTreeApplyTests(unittest.TestCase):

    def test_apply_model_with_decision_tree(self) -> None:
        """Verify ApplyModelNode can apply a decision tree model."""
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)

        # Fit decision tree
        dt_ctx = make_dt_context(store, data_art, def_art)
        dt_node = DecisionTreeNode()
        dt_output = dt_node.run(dt_ctx)

        model_art = dt_output.artifacts[0]
        estimator_art = dt_output.artifacts[1]

        # Create scored datasets using ApplyModelNode
        step_spec = StepSpec(
            step_id="dt-apply",
            node_type="cardre.apply_model",
            node_version="2",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        apply_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[data_art, model_art],
            validated_params={},
            runtime_metadata={},
        )

        apply_node = ApplyModelNode()
        apply_output = apply_node.run(apply_ctx)

        self.assertEqual(len(apply_output.artifacts), 1)
        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))
        self.assertIn("predicted_bad_probability", scored_df.columns)
        self.assertIn("model_artifact_id", scored_df.columns)
        self.assertIn("model_family", scored_df.columns)
        self.assertEqual(
            scored_df["model_family"][0],
            "decision_tree",
        )

    def test_apply_produces_valid_probabilities(self) -> None:
        """Verify predicted probabilities are between 0 and 1."""
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)

        dt_ctx = make_dt_context(store, data_art, def_art)
        dt_node = DecisionTreeNode()
        dt_output = dt_node.run(dt_ctx)

        model_art = dt_output.artifacts[0]

        step_spec = StepSpec(
            step_id="dt-apply-2",
            node_type="cardre.apply_model",
            node_version="2",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        apply_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=step_spec,
            parent_run_steps=[],
            input_artifacts=[data_art, model_art],
            validated_params={},
            runtime_metadata={},
        )

        apply_node = ApplyModelNode()
        apply_output = apply_node.run(apply_ctx)

        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))
        probs = scored_df["predicted_bad_probability"].to_list()
        for p in probs:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)


# ======================================================================
# Integration with ValidationMetricsNode
# ======================================================================

class DecisionTreeValidationTests(unittest.TestCase):

    def test_validation_metrics_with_decision_tree(self) -> None:
        """Verify ValidationMetricsNode works with decision tree scored data."""
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)

        # Fit decision tree
        dt_ctx = make_dt_context(store, data_art, def_art)
        dt_node = DecisionTreeNode()
        dt_output = dt_node.run(dt_ctx)
        model_art = dt_output.artifacts[0]

        # Apply model
        apply_spec = StepSpec(
            step_id="dt-apply-val",
            node_type="cardre.apply_model",
            node_version="2",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        apply_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=apply_spec,
            parent_run_steps=[],
            input_artifacts=[data_art, model_art],
            validated_params={},
            runtime_metadata={},
        )
        apply_node = ApplyModelNode()
        apply_output = apply_node.run(apply_ctx)
        scored_art = apply_output.artifacts[0]

        # Add a synthetic score column since decision tree doesn't produce one
        scored_df = pl.read_parquet(store.artifact_path(scored_art))
        # Score from probability: higher probability = lower score
        score_vals = (1.0 - scored_df["predicted_bad_probability"]) * 1000
        scored_df = scored_df.with_columns(pl.Series("score", score_vals, dtype=pl.Float64))

        from cardre.artifacts import write_parquet_artifact
        scored_with_score = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="scored-with-score", frame=scored_df, metadata={},
        )

        # Validation metrics
        val_spec = StepSpec(
            step_id="dt-validation",
            node_type="cardre.validation_metrics",
            node_version="1",
            category="apply",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        val_ctx = ExecutionContext(
            store=store,
            run_id="test-run",
            plan_version_id="test-pv",
            step_spec=val_spec,
            parent_run_steps=[],
            input_artifacts=[scored_with_score, def_art],
            validated_params={},
            runtime_metadata={},
        )
        val_node = ValidationMetricsNode()
        val_output = val_node.run(val_ctx)

        report = json.loads(store.artifact_path(val_output.artifacts[0]).read_text())
        self.assertIn("train", report)
        train_metrics = report["train"]
        self.assertIn("auc", train_metrics)
        self.assertIsNotNone(train_metrics["auc"])


# ======================================================================
# Determinism
# ======================================================================

class DecisionTreeDeterminismTests(unittest.TestCase):

    def test_same_seed_produces_same_artifacts(self) -> None:
        """Verify deterministic output with same random seed."""
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_dt_context(store, data_art, def_art, run_id="run-1", step_id="dt-1")
        node1 = DecisionTreeNode()
        out1 = node1.run(ctx1)

        ctx2 = make_dt_context(store, data_art, def_art, run_id="run-2", step_id="dt-2")
        node2 = DecisionTreeNode()
        out2 = node2.run(ctx2)

        model1 = json.loads(store.artifact_path(out1.artifacts[0]).read_text())
        model2 = json.loads(store.artifact_path(out2.artifacts[0]).read_text())

        self.assertEqual(model1["model_payload"]["tree_rules"], model2["model_payload"]["tree_rules"])
        self.assertEqual(model1["model_payload"]["tree_depth"], model2["model_payload"]["tree_depth"])
        self.assertEqual(model1["model_payload"]["leaf_count"], model2["model_payload"]["leaf_count"])


if __name__ == "__main__":
    unittest.main()
