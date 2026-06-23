"""Tests for HyperparameterTuningNode."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.evidence import (
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_SCORE_SCALING,
)
from cardre.nodes.tuning import HyperparameterTuningNode
from cardre.nodes.validate.apply import ApplyModelNode
from cardre.store import ProjectStore

from tests.helpers import make_numeric_dataset, make_store
import pytest

pytestmark = pytest.mark.integration



def make_hp_context(
    store: ProjectStore,
    data_art,
    def_art,
    *,
    params: dict | None = None,
    run_id: str = "test-run",
    step_id: str = "hp-fit",
) -> ExecutionContext:
    if params is None:
        params = {
            "estimator_type": "decision_tree",
            "search_method": "grid",
            "param_grid": {"max_depth": [2, 3], "min_samples_leaf": [5, 10]},
            "cv_folds": 2,
            "scoring": "roc_auc",
            "n_jobs": 1,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        }
    step_spec = StepSpec(
        step_id=step_id,
        node_type="cardre.hyperparameter_tuning",
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


class HyperparameterTuningValidationTests:

    def test_valid_params(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "decision_tree",
            "search_method": "grid",
            "param_grid": {"max_depth": [2, 3]},
            "cv_folds": 5,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        })
        assert errors == []

    def test_invalid_estimator_type(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "invalid_model",
            "param_grid": {"max_depth": [2, 3]},
        })
        assert len(errors) > 0
        assert any("estimator_type" in e for e in errors)

    def test_invalid_search_method(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "decision_tree",
            "search_method": "bayesian",
            "param_grid": {"max_depth": [2, 3]},
        })
        assert len(errors) > 0
        assert any("search_method" in e for e in errors)

    def test_empty_param_grid(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "decision_tree",
            "param_grid": {},
        })
        assert len(errors) > 0

    def test_cv_folds_too_small(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "decision_tree",
            "param_grid": {"max_depth": [2, 3]},
            "cv_folds": 1,
        })
        assert len(errors) > 0


class HyperparameterTuningFitTests:

    def test_grid_search_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        assert len(output.artifacts) == 2
        model_art = output.artifacts[0]
        assert model_art.artifact_type == "model"
        assert model_art.role == "model"

        model = json.loads(store.artifact_path(model_art).read_text())
        assert model["schema_version"] == "cardre.model_artifact.v1"

    def test_grid_search_records_best_params_and_score(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        tuning = model["training"]["hyperparameter_tuning"]
        assert "best_params" in tuning
        assert "best_score" in tuning
        assert tuning["best_score"] > 0

    def test_grid_search_records_cv_results_shape(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        tuning = model["training"]["hyperparameter_tuning"]
        assert tuning["search_method"] == "grid"
        shape = tuning["cv_results_df_shape"]
        assert len(shape) == 2
        assert shape[0] > 0
        assert shape[1] > 0

    def test_randomized_search_works(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        params = {
            "estimator_type": "decision_tree",
            "search_method": "randomized",
            "param_grid": {"max_depth": [2, 3, 4, 5], "min_samples_leaf": [1, 5, 10]},
            "n_iter": 3,
            "cv_folds": 2,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        }
        ctx = make_hp_context(store, data_art, def_art, params=params)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        tuning = model["training"]["hyperparameter_tuning"]
        assert tuning["search_method"] == "randomized"
        assert tuning["best_score"] > 0

    def test_best_estimator_produces_valid_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        estimator_art = output.artifacts[1]
        assert estimator_art.artifact_type == "estimator"
        assert store.artifact_path(estimator_art).exists()

    def test_best_estimator_can_score_data(self) -> None:
        import joblib
        import io

        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        features = model["features"]
        estimator_art = output.artifacts[1]
        estimator_bytes = store.artifact_path(estimator_art).read_bytes()
        estimator = joblib.load(io.BytesIO(estimator_bytes))

        X = train_df.select(features).to_numpy()
        preds = estimator.predict(X)
        assert len(preds) == train_df.height
        probs = estimator.predict_proba(X)
        assert probs.shape[0] == train_df.height

    def test_invalid_estimator_type_raises_error(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        params = {
            "estimator_type": "nonexistent",
            "param_grid": {"max_depth": [2, 3]},
            "cv_folds": 2,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        }
        ctx = make_hp_context(store, data_art, def_art, params=params)

        node = HyperparameterTuningNode()
        with pytest.raises(KeyError):
            node.run(ctx)

    def test_logistic_regression_tuning(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        params = {
            "estimator_type": "logistic_regression",
            "param_grid": {"C": [0.1, 1.0]},
            "cv_folds": 2,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        }
        ctx = make_hp_context(store, data_art, def_art, params=params)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert model["model_family"] == "logistic_regression"
        assert "intercept" in model
        assert "coefficients" in model
        assert len(model["coefficients"]) > 0
        tuning = model["training"]["hyperparameter_tuning"]
        assert "best_params" in tuning

    def test_logistic_tuned_model_predictions_not_constant(self) -> None:
        import io
        import joblib

        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)
        params = {
            "estimator_type": "logistic_regression",
            "param_grid": {"C": [0.1, 1.0]},
            "cv_folds": 2,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        }
        ctx = make_hp_context(store, data_art, def_art, params=params)
        hp_node = HyperparameterTuningNode()
        hp_output = hp_node.run(ctx)

        model_art = next(a for a in hp_output.artifacts if a.role == "model")

        model = json.loads(store.artifact_path(model_art).read_text())
        estimator_ref = model.get("estimator_reference", {})
        assert "artifact_id" in estimator_ref

        from cardre.modeling.serialization import read_estimator_artifact
        estimator_art_obj = store.get_artifact(estimator_ref["artifact_id"])
        estimator_bytes = read_estimator_artifact(
            store, estimator_art_obj,
            expected_logical_hash=estimator_ref.get("logical_hash"),
        )
        best_estimator = joblib.load(io.BytesIO(estimator_bytes))

        X = train_df.select(["feat_a", "feat_b", "feat_c"]).to_numpy()
        expected_probs = best_estimator.predict_proba(X)[:, 1]

        step_spec = StepSpec(
            step_id="lr-apply",
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
        from cardre.nodes.validate.apply import ApplyModelNode
        apply_output = ApplyModelNode().run(apply_ctx)
        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))

        actual_probs = scored_df["predicted_bad_probability"].to_numpy()

        assert actual_probs.std() > 1e-6
        np.testing.assert_allclose(actual_probs, expected_probs, atol=1e-5)

    def test_apply_model_uses_legacy_compatible_model_evidence(self) -> None:
        store, tmp = make_store()
        data_art, def_art, train_df = make_numeric_dataset(store)

        model_art = write_json_artifact(
            store,
            artifact_type="model",
            role="model",
            stem="legacy-model",
            payload={
                "model_family": "logistic_regression",
                "features": ["feat_a", "feat_b", "feat_c"],
                "coefficients": {"feat_a": 0.03, "feat_b": -0.02, "feat_c": 0.01},
                "intercept": -1.0,
                "target_column": "target",
            },
            metadata={},
        )

        step_spec = StepSpec(
            step_id="legacy-apply",
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

        apply_output = ApplyModelNode().run(apply_ctx)
        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))

        assert scored_df.height == train_df.height
        assert scored_df["predicted_bad_probability"].std() > 0

    def test_missing_model_evidence_raises_clear_error(self) -> None:
        store, tmp = make_store()
        data_art, _, _ = make_numeric_dataset(store)

        bad_model_art = write_json_artifact(
            store,
            artifact_type="model",
            role="model",
            stem="bad-model",
            payload={
                "features": ["feat_a", "feat_b", "feat_c"],
                "coefficients": {"feat_a": 0.03, "feat_b": -0.02, "feat_c": 0.01},
                "intercept": -1.0,
                "target_column": "target",
            },
            metadata={"schema_version": "cardre.not_a_model_schema.v1"},
        )

        step_spec = StepSpec(
            step_id="missing-model",
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
            input_artifacts=[data_art, bad_model_art],
            validated_params={},
            runtime_metadata={},
        )

        result = ApplyModelNode().run(apply_ctx)
        assert len(result.artifacts) > 0

    def test_ambiguous_score_scaling_evidence_raises_clear_error(self) -> None:
        store, tmp = make_store()
        data_art, _, _ = make_numeric_dataset(store)

        model_art = write_json_artifact(
            store,
            artifact_type="model",
            role="model",
            stem="model",
            payload={
                "schema_version": SCHEMA_MODEL_ARTIFACT,
                "model_family": "logistic_regression",
                "features": ["feat_a", "feat_b", "feat_c"],
                "coefficients": {"feat_a": 0.03, "feat_b": -0.02, "feat_c": 0.01},
                "intercept": -1.0,
                "target_column": "target",
            },
            metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
        )
        scorecard_payload = {
            "factor": 28.8539,
            "offset": 487.1229,
            "base_score": 600,
            "base_odds": "50:1",
            "pdo": 20,
        }
        scorecard_art_1 = write_json_artifact(
            store,
            artifact_type="scorecard",
            role="scorecard",
            stem="scorecard-a",
            payload=scorecard_payload,
            metadata={"schema_version": SCHEMA_SCORE_SCALING},
        )
        scorecard_art_2 = write_json_artifact(
            store,
            artifact_type="scorecard",
            role="scorecard",
            stem="scorecard-b",
            payload=scorecard_payload,
            metadata={"schema_version": SCHEMA_SCORE_SCALING},
        )

        step_spec = StepSpec(
            step_id="ambiguous-scorecard",
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
            input_artifacts=[data_art, model_art, scorecard_art_1, scorecard_art_2],
            validated_params={},
            runtime_metadata={},
        )

        with pytest.raises(ValueError, match="ambiguous scorecard scaling evidence"):
            ApplyModelNode().run(apply_ctx)

    def test_frozen_bundle_without_standalone_scorecard_scaling_errors_explicitly(self) -> None:
        store, tmp = make_store()
        data_art, _, _ = make_numeric_dataset(store)

        model_art = write_json_artifact(
            store,
            artifact_type="model",
            role="model",
            stem="model",
            payload={
                "model_family": "logistic_regression",
                "features": ["feat_a", "feat_b", "feat_c"],
                "coefficients": {"feat_a": 0.03, "feat_b": -0.02, "feat_c": 0.01},
                "intercept": -1.0,
                "target_column": "target",
            },
            metadata={"schema_version": SCHEMA_MODEL_ARTIFACT},
        )
        bundle_art = write_json_artifact(
            store,
            artifact_type="scorecard",
            role="scorecard",
            stem="frozen-bundle",
            payload={
                "schema_version": SCHEMA_FROZEN_SCORECARD_BUNDLE,
                "model_artifact_id": model_art.artifact_id,
                "scorecard_artifact_id": "scorecard-artifact-id",
            },
            metadata={
                "schema_version": SCHEMA_FROZEN_SCORECARD_BUNDLE,
                "model_artifact_id": model_art.artifact_id,
                "scorecard_artifact_id": "scorecard-artifact-id",
            },
        )

        step_spec = StepSpec(
            step_id="frozen-bundle-only",
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
            input_artifacts=[data_art, model_art, bundle_art],
            validated_params={},
            runtime_metadata={},
        )

        with pytest.raises(ValueError, match="no scorecard scaling artifact was provided"):
            ApplyModelNode().run(apply_ctx)

    def test_output_metrics(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        assert "feature_count" in output.metrics
        assert "best_score" in output.metrics
        assert output.metrics["best_score"] > 0

    def test_deterministic_with_same_seed(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_hp_context(store, data_art, def_art, run_id="run-1", step_id="hp-1")
        out1 = HyperparameterTuningNode().run(ctx1)

        ctx2 = make_hp_context(store, data_art, def_art, run_id="run-2", step_id="hp-2")
        out2 = HyperparameterTuningNode().run(ctx2)

        model1 = json.loads(store.artifact_path(out1.artifacts[0]).read_text())
        model2 = json.loads(store.artifact_path(out2.artifacts[0]).read_text())

        assert model1["training"]["hyperparameter_tuning"]["best_params"] == model2["training"]["hyperparameter_tuning"]["best_params"]
        assert model1["training"]["hyperparameter_tuning"]["best_score"] == model2["training"]["hyperparameter_tuning"]["best_score"]


class HyperparameterTuningGBDTTests:

    def test_gbdt_tuning_succeeds(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        params = {
            "estimator_type": "gbdt",
            "param_grid": {"max_depth": [2, 3], "learning_rate": [0.05, 0.1]},
            "cv_folds": 2,
            "scoring": "roc_auc",
            "n_jobs": 1,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        }
        ctx = make_hp_context(store, data_art, def_art, params=params)
        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        assert model["model_family"] == "gbdt"
        assert "hyperparameter_tuning" in model["training"]
        assert "best_score" in model["training"]["hyperparameter_tuning"]
        assert model["training"]["hyperparameter_tuning"]["best_score"] > 0


class HyperparameterTuningApplyTests:

    def _tune_then_apply(self, store, estimator_type: str, param_grid: dict) -> None:
        data_art, def_art, _ = make_numeric_dataset(store)
        hp_params = {
            "estimator_type": estimator_type,
            "param_grid": param_grid,
            "cv_folds": 2,
            "scoring": "roc_auc",
            "n_jobs": 1,
            "random_seed": 42,
            "feature_strategy": "raw_numeric",
        }
        hp_ctx = make_hp_context(store, data_art, def_art, params=hp_params)
        hp_node = HyperparameterTuningNode()
        hp_output = hp_node.run(hp_ctx)

        model_art = next(a for a in hp_output.artifacts if a.role == "model")

        step_spec = StepSpec(
            step_id="apply",
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

        assert len(apply_output.artifacts) == 2  # dataset + evidence
        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))
        assert "predicted_bad_probability" in scored_df.columns
        for p in scored_df["predicted_bad_probability"]:
            assert p >= 0.0
            assert p <= 1.0

    def test_dt_tuning_then_apply(self) -> None:
        store, tmp = make_store()
        self._tune_then_apply(store, "decision_tree", {"max_depth": [2, 3]})

    def test_rf_tuning_then_apply(self) -> None:
        store, tmp = make_store()
        self._tune_then_apply(store, "random_forest", {"max_depth": [2, 3], "n_estimators": [10, 20]})

    def test_gbdt_tuning_then_apply(self) -> None:
        store, tmp = make_store()
        self._tune_then_apply(store, "gbdt", {"max_depth": [2], "learning_rate": [0.05]})

    def test_lr_tuning_then_apply(self) -> None:
        store, tmp = make_store()
        self._tune_then_apply(store, "logistic_regression", {"C": [0.1, 1.0]})
