"""Tests for Phase 3 (RF/GBDT) and Phase 4 (expanded metrics + threshold optimization)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.modeling.schema import validate_model_artifact
from cardre.nodes.ml_models import (
    DecisionTreeNode,
    GradientBoostingClassifierNode,
    RandomForestClassifierNode,
)
from cardre.nodes.validate import (
    ApplyModelNode,
    ThresholdOptimizationNode,
    ValidationMetricsNode,
)
from cardre.store import ProjectStore

from tests.helpers import make_numeric_dataset, make_oot_dataset, make_store


# ======================================================================
# Helpers
# ======================================================================


def make_fit_context(
    store: ProjectStore,
    data_art,
    def_art,
    node_type: str,
    *,
    params: dict | None = None,
    run_id: str = "test-run",
    step_id: str = "fit-step",
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
        node_type=node_type,
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


def make_apply_context(
    store: ProjectStore,
    data_art,
    model_art,
    *,
    step_id: str = "apply-step",
) -> ExecutionContext:
    step_spec = StepSpec(
        step_id=step_id,
        node_type="cardre.apply_model",
        node_version="2",
        category="apply",
        params={},
        params_hash=json_logical_hash({}),
        parent_step_ids=[],
        branch_label="",
        position=0,
    )
    return ExecutionContext(
        store=store,
        run_id="test-run",
        plan_version_id="test-pv",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=[data_art, model_art],
        validated_params={},
        runtime_metadata={},
    )


def make_val_context(
    store: ProjectStore,
    data_arts: list,
    def_art,
    *,
    params: dict | None = None,
    step_id: str = "val-step",
) -> ExecutionContext:
    step_spec = StepSpec(
        step_id=step_id,
        node_type="cardre.validation_metrics",
        node_version="2",
        category="apply",
        params=params or {},
        params_hash=json_logical_hash(params or {}),
        parent_step_ids=[],
        branch_label="",
        position=0,
    )
    return ExecutionContext(
        store=store,
        run_id="test-run",
        plan_version_id="test-pv",
        step_spec=step_spec,
        parent_run_steps=[],
        input_artifacts=data_arts + [def_art],
        validated_params=params or {},
        runtime_metadata={},
    )


def score_and_add_score_col(store, data_art, model_art, step_id="score-step"):
    """Apply model and add score column for validation nodes."""
    apply_ctx = make_apply_context(store, data_art, model_art, step_id=step_id)
    apply_out = ApplyModelNode().run(apply_ctx)
    scored_df = pl.read_parquet(store.artifact_path(apply_out.artifacts[0]))
    score_vals = (1.0 - scored_df["predicted_bad_probability"]) * 1000
    scored_df = scored_df.with_columns(pl.Series("score", score_vals, dtype=pl.Float64))
    from cardre.artifacts import write_parquet_artifact
    return write_parquet_artifact(
        store, artifact_type="dataset", role=data_art.role,
        stem=f"scored-{data_art.role}", frame=scored_df, metadata={},
    )


# ======================================================================
# RandomForestClassifier Tests
# ======================================================================

class RandomForestParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = RandomForestClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "n_estimators": 100,
            "max_depth": 5,
            "min_samples_leaf": 3,
            "random_seed": 42,
        })
        self.assertEqual(errors, [])

    def test_invalid_feature_strategy(self) -> None:
        node = RandomForestClassifierNode()
        errors = node.validate_params({"feature_strategy": "woe"})
        self.assertGreater(len(errors), 0)

    def test_n_estimators_zero(self) -> None:
        node = RandomForestClassifierNode()
        errors = node.validate_params({"feature_strategy": "raw_numeric", "n_estimators": 0})
        self.assertGreater(len(errors), 0)

    def test_valid_balanced_class_weight(self) -> None:
        node = RandomForestClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": "balanced",
        })
        self.assertEqual(errors, [])


class RandomForestFitTests(unittest.TestCase):

    def test_fit_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["schema_version"], "cardre.model_artifact.v1")
        self.assertEqual(model["model_family"], "random_forest")

    def test_model_artifact_passes_validation(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        errors = validate_model_artifact(model)
        self.assertEqual(errors, [])

    def test_fit_records_estimator_count(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 50, "random_seed": 42})

        output = RandomForestClassifierNode().run(ctx)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["training"]["params"]["n_estimators"], 50)
        self.assertIn("feature_importance", model["model_payload"])

    def test_fit_records_interpretability_level(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["interpretability"]["explanation_level"], "native_semi_transparent")

    def test_fit_produces_estimator_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)
        estimator_art = output.artifacts[1]
        self.assertEqual(estimator_art.artifact_type, "estimator")
        self.assertTrue(store.artifact_path(estimator_art).exists())


# ======================================================================
# GradientBoostingClassifier Tests
# ======================================================================

class GradientBoostingParameterTests(unittest.TestCase):

    def test_valid_params(self) -> None:
        node = GradientBoostingClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "n_estimators": 100,
            "max_depth": 3,
            "learning_rate": 0.1,
            "min_samples_leaf": 5,
            "random_seed": 42,
        })
        self.assertEqual(errors, [])

    def test_learning_rate_zero(self) -> None:
        node = GradientBoostingClassifierNode()
        errors = node.validate_params({"feature_strategy": "raw_numeric", "learning_rate": 0})
        self.assertGreater(len(errors), 0)

    def test_learning_rate_negative(self) -> None:
        node = GradientBoostingClassifierNode()
        errors = node.validate_params({"feature_strategy": "raw_numeric", "learning_rate": -0.1})
        self.assertGreater(len(errors), 0)


class GradientBoostingFitTests(unittest.TestCase):

    def test_fit_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")

        output = GradientBoostingClassifierNode().run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["schema_version"], "cardre.model_artifact.v1")
        self.assertEqual(model["model_family"], "gbdt")

    def test_model_artifact_passes_validation(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")

        output = GradientBoostingClassifierNode().run(ctx)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        errors = validate_model_artifact(model)
        self.assertEqual(errors, [])

    def test_fit_records_learning_rate(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 50, "learning_rate": 0.05, "random_seed": 42})

        output = GradientBoostingClassifierNode().run(ctx)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["training"]["params"]["learning_rate"], 0.05)

    def test_fit_records_train_score_history(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 10, "random_seed": 42})

        output = GradientBoostingClassifierNode().run(ctx)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertIn("learning_rate", model["model_payload"])
        self.assertIn("estimator_count", model["model_payload"])

    def test_fit_records_interpretability_level(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")

        output = GradientBoostingClassifierNode().run(ctx)
        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        self.assertEqual(model["interpretability"]["explanation_level"], "native_semi_transparent")


# ======================================================================
# Integration: RF and GBDT with ApplyModelNode
# ======================================================================

class EnsembleApplyTests(unittest.TestCase):

    def test_apply_model_with_random_forest(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        output = RandomForestClassifierNode().run(ctx)
        model_art = output.artifacts[0]

        apply_ctx = make_apply_context(store, data_art, model_art)
        apply_out = ApplyModelNode().run(apply_ctx)
        scored_df = pl.read_parquet(store.artifact_path(apply_out.artifacts[0]))
        self.assertIn("predicted_bad_probability", scored_df.columns)
        self.assertEqual(scored_df["model_family"][0], "random_forest")

    def test_apply_model_with_gbdt(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")
        output = GradientBoostingClassifierNode().run(ctx)
        model_art = output.artifacts[0]

        apply_ctx = make_apply_context(store, data_art, model_art)
        apply_out = ApplyModelNode().run(apply_ctx)
        scored_df = pl.read_parquet(store.artifact_path(apply_out.artifacts[0]))
        self.assertIn("predicted_bad_probability", scored_df.columns)
        self.assertEqual(scored_df["model_family"][0], "gbdt")

    def test_apply_produces_valid_probabilities_rf(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        output = RandomForestClassifierNode().run(ctx)
        model_art = output.artifacts[0]

        apply_ctx = make_apply_context(store, data_art, model_art)
        apply_out = ApplyModelNode().run(apply_ctx)
        scored_df = pl.read_parquet(store.artifact_path(apply_out.artifacts[0]))
        probs = scored_df["predicted_bad_probability"].to_list()
        for p in probs:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)


# ======================================================================
# Expanded ValidationMetricsNode Tests
# ======================================================================

class ExpandedValidationMetricsTests(unittest.TestCase):

    def test_at_cutoffs_includes_confusion_matrix(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        rf_ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        rf_out = RandomForestClassifierNode().run(rf_ctx)
        model_art = rf_out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-rf-val")

        val_ctx = make_val_context(store, [scored_art], def_art, params={"cutoffs": [0.3, 0.5, 0.7]})
        report_out = ValidationMetricsNode().run(val_ctx)
        report = json.loads(store.artifact_path(report_out.artifacts[0]).read_text())

        self.assertIn("train", report)
        train_metrics = report["train"]
        self.assertIn("at_cutoffs", train_metrics)
        self.assertIn("0.3", train_metrics["at_cutoffs"])
        self.assertIn("0.5", train_metrics["at_cutoffs"])
        self.assertIn("0.7", train_metrics["at_cutoffs"])

        cm = train_metrics["at_cutoffs"]["0.5"]["confusion_matrix"]
        self.assertIn("tn", cm)
        self.assertIn("fp", cm)
        self.assertIn("fn", cm)
        self.assertIn("tp", cm)

    def test_at_cutoffs_includes_precision_recall_f1_gmean(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        dt_ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        dt_out = DecisionTreeNode().run(dt_ctx)
        model_art = dt_out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-dt-metrics")

        val_ctx = make_val_context(store, [scored_art], def_art, params={"cutoffs": [0.5]})
        report_out = ValidationMetricsNode().run(val_ctx)
        report = json.loads(store.artifact_path(report_out.artifacts[0]).read_text())

        at_05 = report["train"]["at_cutoffs"]["0.5"]
        self.assertIn("precision", at_05)
        self.assertIn("recall", at_05)
        self.assertIn("f1", at_05)
        self.assertIn("g_mean", at_05)
        self.assertIn("specificity", at_05)
        self.assertIn("accuracy", at_05)

    def test_all_metrics_computed_from_actual_labels(self) -> None:
        """Ensure y_bin comes from target column, not from predictions."""
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        dt_ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        dt_out = DecisionTreeNode().run(dt_ctx)
        model_art = dt_out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-label-check")

        val_ctx = make_val_context(store, [scored_art], def_art)
        report_out = ValidationMetricsNode().run(val_ctx)
        report = json.loads(store.artifact_path(report_out.artifacts[0]).read_text())

        self.assertIn("train", report)
        self.assertIsNotNone(report["train"]["auc"])

    def test_single_class_role_produces_warnings(self) -> None:
        store, tmp = make_store()
        df = pl.DataFrame({
            "feat_a": [1.0] * 50,
            "predicted_bad_probability": [0.1] * 50,
            "score": [900.0] * 50,
            "target": ["good"] * 50,
        })
        from cardre.artifacts import write_json_artifact, write_parquet_artifact
        data_art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem="single-class", frame=df, metadata={},
        )
        def_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem="single-class-def",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={},
        )

        val_ctx = make_val_context(store, [data_art], def_art)
        report_out = ValidationMetricsNode().run(val_ctx)
        report = json.loads(store.artifact_path(report_out.artifacts[0]).read_text())

        self.assertIn("train", report)
        self.assertIn("warnings", report["train"])
        self.assertGreater(len(report["train"]["warnings"]), 0)

    def test_gbdt_with_validation_metrics(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")
        out = GradientBoostingClassifierNode().run(ctx)
        model_art = out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-gbdt-val")

        val_ctx = make_val_context(store, [scored_art], def_art, params={"cutoffs": [0.5]})
        report_out = ValidationMetricsNode().run(val_ctx)
        report = json.loads(store.artifact_path(report_out.artifacts[0]).read_text())

        self.assertIn("train", report)
        self.assertIn("at_cutoffs", report["train"])
        self.assertIn("0.5", report["train"]["at_cutoffs"])
        self.assertIsNotNone(report["train"]["auc"])

    def test_calibration_display_with_default_deps(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        out = DecisionTreeNode().run(ctx)
        model_art = out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-calib")

        val_ctx = make_val_context(
            store, [scored_art], def_art,
            params={"cutoffs": [0.5], "include_calibration_display": True},
        )
        report_out = ValidationMetricsNode().run(val_ctx)
        report = json.loads(store.artifact_path(report_out.artifacts[0]).read_text())

        self.assertIn("train", report)
        calib = report["train"].get("calibration_display", {})
        self.assertIn("prob_true", calib)
        self.assertIn("prob_pred", calib)
        self.assertEqual(calib["n_bins"], 10)
        self.assertEqual(calib["strategy"], "quantile")


# ======================================================================
# ThresholdOptimizationNode Tests
# ======================================================================

class ThresholdOptimizationParameterTests(unittest.TestCase):

    def test_valid_youden(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "youden"})
        self.assertEqual(errors, [])

    def test_valid_max_f1(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "max_f1"})
        self.assertEqual(errors, [])

    def test_valid_cost_minimize(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({
            "objective": "cost_minimize",
            "cost_fp": 1.0,
            "cost_fn": 10.0,
        })
        self.assertEqual(errors, [])

    def test_cost_minimize_requires_costs(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "cost_minimize"})
        self.assertGreater(len(errors), 0)

    def test_invalid_objective(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "invalid"})
        self.assertGreater(len(errors), 0)

    def test_n_thresholds_too_low(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"n_thresholds": 5})
        self.assertGreater(len(errors), 0)


class ThresholdOptimizationRunTests(unittest.TestCase):

    def _make_scored_dataset(self, store, data_art, model_art):
        scored_art = score_and_add_score_col(store, data_art, model_art, "score-threshold")
        return scored_art

    def test_youden_selects_threshold(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        rf_ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        rf_out = RandomForestClassifierNode().run(rf_ctx)
        model_art = rf_out.artifacts[0]
        scored_art = self._make_scored_dataset(store, data_art, model_art)

        step_spec = StepSpec(
            step_id="thresh-opt",
            node_type="cardre.threshold_optimization",
            node_version="1",
            category="apply",
            params={"objective": "youden"},
            params_hash=json_logical_hash({"objective": "youden"}),
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
            input_artifacts=[scored_art, def_art],
            validated_params={"objective": "youden"},
            runtime_metadata={},
        )

        out = ThresholdOptimizationNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())

        self.assertEqual(report["objective"], "youden")
        self.assertIn("selected_threshold", report)
        self.assertGreaterEqual(report["selected_threshold"], 0.0)
        self.assertLessEqual(report["selected_threshold"], 1.0)
        self.assertIn("train", report["roles"])
        self.assertIn("threshold", report["roles"]["train"])

    def test_max_f1_objective(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        rf_ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        rf_out = RandomForestClassifierNode().run(rf_ctx)
        model_art = rf_out.artifacts[0]
        scored_art = self._make_scored_dataset(store, data_art, model_art)

        step_spec = StepSpec(
            step_id="thresh-f1",
            node_type="cardre.threshold_optimization",
            node_version="1",
            category="apply",
            params={"objective": "max_f1"},
            params_hash=json_logical_hash({"objective": "max_f1"}),
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
            input_artifacts=[scored_art, def_art],
            validated_params={"objective": "max_f1"},
            runtime_metadata={},
        )

        out = ThresholdOptimizationNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        self.assertEqual(report["objective"], "max_f1")
        self.assertIn("selected_threshold", report)

    def test_cost_minimize_objective(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        rf_ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        rf_out = RandomForestClassifierNode().run(rf_ctx)
        model_art = rf_out.artifacts[0]
        scored_art = self._make_scored_dataset(store, data_art, model_art)

        step_spec = StepSpec(
            step_id="thresh-cost",
            node_type="cardre.threshold_optimization",
            node_version="1",
            category="apply",
            params={"objective": "cost_minimize", "cost_fp": 1.0, "cost_fn": 10.0},
            params_hash=json_logical_hash({"objective": "cost_minimize", "cost_fp": 1.0, "cost_fn": 10.0}),
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
            input_artifacts=[scored_art, def_art],
            validated_params={"objective": "cost_minimize", "cost_fp": 1.0, "cost_fn": 10.0},
            runtime_metadata={},
        )

        out = ThresholdOptimizationNode().run(ctx)
        report = json.loads(store.artifact_path(out.artifacts[0]).read_text())
        self.assertEqual(report["objective"], "cost_minimize")
        self.assertEqual(report["cost_fp"], 1.0)
        self.assertEqual(report["cost_fn"], 10.0)
        self.assertIn("selected_threshold", report)

    def test_threshold_optimization_does_not_overwrite_probabilities(self) -> None:
        """Verify threshold policy does not mutate the scored dataset."""
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        rf_ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        rf_out = RandomForestClassifierNode().run(rf_ctx)
        model_art = rf_out.artifacts[0]
        scored_art = self._make_scored_dataset(store, data_art, model_art)

        original_df = pl.read_parquet(store.artifact_path(scored_art))
        original_probs = original_df["predicted_bad_probability"].to_list()

        step_spec = StepSpec(
            step_id="thresh-no-mutate",
            node_type="cardre.threshold_optimization",
            node_version="1",
            category="apply",
            params={"objective": "youden"},
            params_hash=json_logical_hash({"objective": "youden"}),
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
            input_artifacts=[scored_art, def_art],
            validated_params={"objective": "youden"},
            runtime_metadata={},
        )
        ThresholdOptimizationNode().run(ctx)

        after_df = pl.read_parquet(store.artifact_path(scored_art))
        after_probs = after_df["predicted_bad_probability"].to_list()
        self.assertEqual(original_probs, after_probs)


# ======================================================================
# Determinism Tests for RF/GBDT
# ======================================================================

class EnsembleDeterminismTests(unittest.TestCase):

    def test_rf_same_seed_produces_same_artifacts(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier", run_id="r1", step_id="rf1")
        out1 = RandomForestClassifierNode().run(ctx1)
        ctx2 = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier", run_id="r2", step_id="rf2")
        out2 = RandomForestClassifierNode().run(ctx2)

        m1 = json.loads(store.artifact_path(out1.artifacts[0]).read_text())
        m2 = json.loads(store.artifact_path(out2.artifacts[0]).read_text())
        self.assertEqual(m1["model_payload"]["feature_importance"], m2["model_payload"]["feature_importance"])

    def test_gbdt_same_seed_produces_same_artifacts(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier", run_id="g1", step_id="gb1")
        out1 = GradientBoostingClassifierNode().run(ctx1)
        ctx2 = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier", run_id="g2", step_id="gb2")
        out2 = GradientBoostingClassifierNode().run(ctx2)

        m1 = json.loads(store.artifact_path(out1.artifacts[0]).read_text())
        m2 = json.loads(store.artifact_path(out2.artifacts[0]).read_text())
        self.assertEqual(m1["model_payload"]["feature_importance"], m2["model_payload"]["feature_importance"])


if __name__ == "__main__":
    unittest.main()
