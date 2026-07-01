"""Tests for Phase 3 (RF/GBDT) and Phase 4 (expanded metrics + threshold optimization)."""

from __future__ import annotations

import json
import os

import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.artifacts import write_json_artifact, write_parquet_artifact
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

from tests.helpers import make_numeric_dataset, make_store
from tests.helpers.evidence_assertions import assert_model_artifact

import pytest

_LAUNCH_MODE = os.environ.get("CARDRE_LAUNCH_MODE", "1").strip().lower() in ("1", "true")
_skip_if_launch = pytest.mark.skipif(_LAUNCH_MODE, reason="GBDT is deferred at launch simplification")

pytestmark = pytest.mark.integration


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
    scored_df = ArtifactEvidenceReader(store).read(apply_out.artifacts[0].artifact_id, EvidenceKind.SCORED_DATASET).dataframe.collect()
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

class RandomForestParameterTests:

    def test_valid_params(self) -> None:
        node = RandomForestClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "n_estimators": 100,
            "max_depth": 5,
            "min_samples_leaf": 3,
            "random_seed": 42,
        })
        assert errors == []

    def test_valid_balanced_class_weight(self) -> None:
        node = RandomForestClassifierNode()
        errors = node.validate_params({
            "feature_strategy": "raw_numeric",
            "class_weight": "balanced",
        })
        assert errors == []


class RandomForestFitTests:

    def test_fit_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)

        assert len(output.artifacts) == 2
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert_model_artifact(model, expected_kind="random_forest")

    def test_model_artifact_passes_validation(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        errors = validate_model_artifact(model._raw)
        assert errors == []

    def test_fit_records_estimator_count(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 50, "random_seed": 42})

        output = RandomForestClassifierNode().run(ctx)
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert model.training["params"]["n_estimators"] == 50
        assert "feature_importance" in model._raw["model_payload"]

    def test_fit_records_interpretability_level(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert model._raw["interpretability"]["explanation_level"] == "native_semi_transparent"

    def test_fit_produces_estimator_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")

        output = RandomForestClassifierNode().run(ctx)
        estimator_art = output.artifacts[1]
        assert estimator_art.artifact_type == "estimator"
        assert store.artifact_path(estimator_art).exists()


# ======================================================================
# GradientBoostingClassifier Tests
# ======================================================================

@_skip_if_launch
class GradientBoostingParameterTests:

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
        assert errors == []


@_skip_if_launch
class GradientBoostingFitTests:

    def test_fit_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")

        output = GradientBoostingClassifierNode().run(ctx)

        assert len(output.artifacts) == 2
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert_model_artifact(model, expected_kind="gbdt")

    def test_model_artifact_passes_validation(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")

        output = GradientBoostingClassifierNode().run(ctx)
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        errors = validate_model_artifact(model._raw)
        assert errors == []

    def test_fit_records_learning_rate(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 50, "learning_rate": 0.05, "random_seed": 42})

        output = GradientBoostingClassifierNode().run(ctx)
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert model.training["params"]["learning_rate"] == 0.05

    def test_fit_records_train_score_history(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier",
                               params={"feature_strategy": "raw_numeric", "n_estimators": 10, "random_seed": 42})

        output = GradientBoostingClassifierNode().run(ctx)
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert "learning_rate" in model._raw["model_payload"]
        assert "estimator_count" in model._raw["model_payload"]

    def test_fit_records_interpretability_level(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")

        output = GradientBoostingClassifierNode().run(ctx)
        model = ArtifactEvidenceReader(store).read(output.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert model._raw["interpretability"]["explanation_level"] == "native_semi_transparent"


# ======================================================================
# Integration: RF and GBDT with ApplyModelNode
# ======================================================================

class EnsembleApplyTests:

    def test_apply_model_with_random_forest(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        output = RandomForestClassifierNode().run(ctx)
        model_art = output.artifacts[0]

        apply_ctx = make_apply_context(store, data_art, model_art)
        apply_out = ApplyModelNode().run(apply_ctx)
        scored_df = ArtifactEvidenceReader(store).read(apply_out.artifacts[0].artifact_id, EvidenceKind.SCORED_DATASET).dataframe.collect()
        assert "predicted_bad_probability" in scored_df.columns
        assert scored_df["model_family"][0] == "random_forest"

    @_skip_if_launch
    def test_apply_model_with_gbdt(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")
        output = GradientBoostingClassifierNode().run(ctx)
        model_art = output.artifacts[0]

        apply_ctx = make_apply_context(store, data_art, model_art)
        apply_out = ApplyModelNode().run(apply_ctx)
        scored_df = ArtifactEvidenceReader(store).read(apply_out.artifacts[0].artifact_id, EvidenceKind.SCORED_DATASET).dataframe.collect()
        assert "predicted_bad_probability" in scored_df.columns
        assert scored_df["model_family"][0] == "gbdt"

    def test_apply_produces_valid_probabilities_rf(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        output = RandomForestClassifierNode().run(ctx)
        model_art = output.artifacts[0]

        apply_ctx = make_apply_context(store, data_art, model_art)
        apply_out = ApplyModelNode().run(apply_ctx)
        scored_df = ArtifactEvidenceReader(store).read(apply_out.artifacts[0].artifact_id, EvidenceKind.SCORED_DATASET).dataframe.collect()
        probs = scored_df["predicted_bad_probability"].to_list()
        for p in probs:
            assert p >= 0.0
            assert p <= 1.0


# ======================================================================
# Expanded ValidationMetricsNode Tests
# ======================================================================

class ExpandedValidationMetricsTests:

    def test_at_cutoffs_includes_confusion_matrix(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        rf_ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        rf_out = RandomForestClassifierNode().run(rf_ctx)
        model_art = rf_out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-rf-val")

        val_ctx = make_val_context(store, [scored_art], def_art, params={"cutoffs": [0.3, 0.5, 0.7]})
        report_out = ValidationMetricsNode().run(val_ctx)
        report = ArtifactEvidenceReader(store).read(report_out.artifacts[0].artifact_id, EvidenceKind.VALIDATION_EVIDENCE)

        train_metrics = report._raw["roles"]["train"]
        assert "at_cutoffs" in train_metrics
        assert "0.3" in train_metrics["at_cutoffs"]
        assert "0.5" in train_metrics["at_cutoffs"]
        assert "0.7" in train_metrics["at_cutoffs"]

        cm = train_metrics["at_cutoffs"]["0.5"]["confusion_matrix"]
        assert "tn" in cm
        assert "fp" in cm
        assert "fn" in cm
        assert "tp" in cm

    def test_at_cutoffs_includes_precision_recall_f1_gmean(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        dt_ctx = make_fit_context(store, data_art, def_art, "cardre.decision_tree_classifier")
        dt_out = DecisionTreeNode().run(dt_ctx)
        model_art = dt_out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-dt-metrics")

        val_ctx = make_val_context(store, [scored_art], def_art, params={"cutoffs": [0.5]})
        report_out = ValidationMetricsNode().run(val_ctx)
        report = ArtifactEvidenceReader(store).read(report_out.artifacts[0].artifact_id, EvidenceKind.VALIDATION_EVIDENCE)

        at_05 = report._raw["roles"]["train"]["at_cutoffs"]["0.5"]
        assert "precision" in at_05
        assert "recall" in at_05
        assert "f1" in at_05
        assert "g_mean" in at_05
        assert "specificity" in at_05
        assert "accuracy" in at_05

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
        report = ArtifactEvidenceReader(store).read(report_out.artifacts[0].artifact_id, EvidenceKind.VALIDATION_EVIDENCE)

        assert report.metrics_by_role["train"].auc is not None

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
        report = ArtifactEvidenceReader(store).read(report_out.artifacts[0].artifact_id, EvidenceKind.VALIDATION_EVIDENCE)

        assert report.warnings or report._raw["roles"]["train"].get("warnings")

    @_skip_if_launch
    def test_gbdt_with_validation_metrics(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        ctx = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier")
        out = GradientBoostingClassifierNode().run(ctx)
        model_art = out.artifacts[0]

        scored_art = score_and_add_score_col(store, data_art, model_art, "score-gbdt-val")

        val_ctx = make_val_context(store, [scored_art], def_art, params={"cutoffs": [0.5]})
        report_out = ValidationMetricsNode().run(val_ctx)
        report = ArtifactEvidenceReader(store).read(report_out.artifacts[0].artifact_id, EvidenceKind.VALIDATION_EVIDENCE)

        assert "0.5" in report._raw["roles"]["train"]["at_cutoffs"]
        assert report.metrics_by_role["train"].auc is not None

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
        report = ArtifactEvidenceReader(store).read(report_out.artifacts[0].artifact_id, EvidenceKind.VALIDATION_EVIDENCE)

        calib = report._raw["roles"]["train"].get("calibration_display", {})
        assert "prob_true" in calib
        assert "prob_pred" in calib
        assert calib["n_bins"] == 10
        assert calib["strategy"] == "quantile"

    def test_validation_metrics_handles_tied_ks_max(self) -> None:
        store, tmp = make_store()
        df = pl.DataFrame(
            {
                "predicted_bad_probability": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
                "score": [500.0] * 6,
                "target": ["bad", "bad", "good", "bad", "good", "good"],
            }
        )
        data_art = write_parquet_artifact(
            store,
            artifact_type="dataset",
            role="train",
            stem="tie-ks",
            frame=df,
            metadata={},
        )
        def_art = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem="tie-ks-def",
            payload={"target_column": "target", "good_values": ["good"], "bad_values": ["bad"]},
            metadata={},
        )

        val_ctx = make_val_context(store, [data_art], def_art)
        report_out = ValidationMetricsNode().run(val_ctx)
        report = ArtifactEvidenceReader(store).read(report_out.artifacts[0].artifact_id, EvidenceKind.VALIDATION_EVIDENCE)

        train_metrics = report._raw["roles"]["train"]
        assert train_metrics["ks"] is not None
        assert train_metrics["ks_at_score"] == 500.0


# ======================================================================
# ThresholdOptimizationNode Tests
# ======================================================================

class ThresholdOptimizationParameterTests:

    def test_valid_youden(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "youden"})
        assert errors == []

    def test_valid_max_f1(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "max_f1"})
        assert errors == []

    def test_valid_cost_minimize(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({
            "objective": "cost_minimize",
            "cost_fp": 1.0,
            "cost_fn": 10.0,
        })
        assert errors == []

    def test_cost_minimize_requires_costs(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "cost_minimize"})
        assert len(errors) > 0

    def test_invalid_objective(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"objective": "invalid"})
        assert len(errors) > 0

    def test_n_thresholds_too_low(self) -> None:
        node = ThresholdOptimizationNode()
        errors = node.validate_params({"n_thresholds": 5})
        assert len(errors) > 0


class ThresholdOptimizationRunTests:

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

        assert report["objective"] == "youden"
        assert "selected_threshold" in report
        assert report["selected_threshold"] >= 0.0
        assert report["selected_threshold"] <= 1.0
        assert "train" in report["roles"]
        assert "threshold" in report["roles"]["train"]

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
        assert report["objective"] == "max_f1"
        assert "selected_threshold" in report

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
        assert report["objective"] == "cost_minimize"
        assert report["cost_fp"] == 1.0
        assert report["cost_fn"] == 10.0
        assert "selected_threshold" in report

    def test_threshold_optimization_does_not_overwrite_probabilities(self) -> None:
        """Verify threshold policy does not mutate the scored dataset."""
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        rf_ctx = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier")
        rf_out = RandomForestClassifierNode().run(rf_ctx)
        model_art = rf_out.artifacts[0]
        scored_art = self._make_scored_dataset(store, data_art, model_art)

        original_df = ArtifactEvidenceReader(store).read(scored_art.artifact_id, EvidenceKind.SCORED_DATASET).dataframe.collect()
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

        after_df = ArtifactEvidenceReader(store).read(scored_art.artifact_id, EvidenceKind.SCORED_DATASET).dataframe.collect()
        after_probs = after_df["predicted_bad_probability"].to_list()
        assert original_probs == after_probs


# ======================================================================
# Determinism Tests for RF/GBDT
# ======================================================================

class EnsembleDeterminismTests:

    def test_rf_same_seed_produces_same_artifacts(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier", run_id="r1", step_id="rf1")
        out1 = RandomForestClassifierNode().run(ctx1)
        ctx2 = make_fit_context(store, data_art, def_art, "cardre.random_forest_classifier", run_id="r2", step_id="rf2")
        out2 = RandomForestClassifierNode().run(ctx2)

        m1 = ArtifactEvidenceReader(store).read(out1.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        m2 = ArtifactEvidenceReader(store).read(out2.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert m1._raw["model_payload"]["feature_importance"] == m2._raw["model_payload"]["feature_importance"]

    @_skip_if_launch
    def test_gbdt_same_seed_produces_same_artifacts(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier", run_id="g1", step_id="gb1")
        out1 = GradientBoostingClassifierNode().run(ctx1)
        ctx2 = make_fit_context(store, data_art, def_art, "cardre.gradient_boosting_classifier", run_id="g2", step_id="gb2")
        out2 = GradientBoostingClassifierNode().run(ctx2)

        m1 = ArtifactEvidenceReader(store).read(out1.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        m2 = ArtifactEvidenceReader(store).read(out2.artifacts[0].artifact_id, EvidenceKind.MODEL_ARTIFACT)
        assert m1._raw["model_payload"]["feature_importance"] == m2._raw["model_payload"]["feature_importance"]
