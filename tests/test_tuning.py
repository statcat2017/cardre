"""Tests for HyperparameterTuningNode."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes.tuning import HyperparameterTuningNode
from cardre.nodes.validate.apply import ApplyModelNode
from cardre.store import ProjectStore

from tests.helpers import make_numeric_dataset, make_store


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


class HyperparameterTuningValidationTests(unittest.TestCase):

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
        self.assertEqual(errors, [])

    def test_invalid_estimator_type(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "invalid_model",
            "param_grid": {"max_depth": [2, 3]},
        })
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("estimator_type" in e for e in errors))

    def test_invalid_search_method(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "decision_tree",
            "search_method": "bayesian",
            "param_grid": {"max_depth": [2, 3]},
        })
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("search_method" in e for e in errors))

    def test_empty_param_grid(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "decision_tree",
            "param_grid": {},
        })
        self.assertGreater(len(errors), 0)

    def test_cv_folds_too_small(self) -> None:
        node = HyperparameterTuningNode()
        errors = node.validate_params({
            "estimator_type": "decision_tree",
            "param_grid": {"max_depth": [2, 3]},
            "cv_folds": 1,
        })
        self.assertGreater(len(errors), 0)


class HyperparameterTuningFitTests(unittest.TestCase):

    def test_grid_search_produces_v1_model_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        self.assertEqual(len(output.artifacts), 2)
        model_art = output.artifacts[0]
        self.assertEqual(model_art.artifact_type, "model")
        self.assertEqual(model_art.role, "model")

        model = json.loads(store.artifact_path(model_art).read_text())
        self.assertEqual(model["schema_version"], "cardre.model_artifact.v1")

    def test_grid_search_records_best_params_and_score(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        tuning = model["training"]["hyperparameter_tuning"]
        self.assertIn("best_params", tuning)
        self.assertIn("best_score", tuning)
        self.assertGreater(tuning["best_score"], 0)

    def test_grid_search_records_cv_results_shape(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        model = json.loads(store.artifact_path(output.artifacts[0]).read_text())
        tuning = model["training"]["hyperparameter_tuning"]
        self.assertEqual(tuning["search_method"], "grid")
        shape = tuning["cv_results_df_shape"]
        self.assertEqual(len(shape), 2)
        self.assertGreater(shape[0], 0)
        self.assertGreater(shape[1], 0)

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
        self.assertEqual(tuning["search_method"], "randomized")
        self.assertGreater(tuning["best_score"], 0)

    def test_best_estimator_produces_valid_artifact(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        estimator_art = output.artifacts[1]
        self.assertEqual(estimator_art.artifact_type, "estimator")
        self.assertTrue(
            store.artifact_path(estimator_art).exists(),
            "Estimator artifact file must exist on disk",
        )

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
        self.assertEqual(len(preds), train_df.height)
        probs = estimator.predict_proba(X)
        self.assertEqual(probs.shape[0], train_df.height)

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
        with self.assertRaises(KeyError):
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
        self.assertEqual(model["model_family"], "logistic_regression")
        tuning = model["training"]["hyperparameter_tuning"]
        self.assertIn("best_params", tuning)

    def test_output_metrics(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)
        ctx = make_hp_context(store, data_art, def_art)

        node = HyperparameterTuningNode()
        output = node.run(ctx)

        self.assertIn("feature_count", output.metrics)
        self.assertIn("best_score", output.metrics)
        self.assertGreater(output.metrics["best_score"], 0)

    def test_deterministic_with_same_seed(self) -> None:
        store, tmp = make_store()
        data_art, def_art, _ = make_numeric_dataset(store)

        ctx1 = make_hp_context(store, data_art, def_art, run_id="run-1", step_id="hp-1")
        out1 = HyperparameterTuningNode().run(ctx1)

        ctx2 = make_hp_context(store, data_art, def_art, run_id="run-2", step_id="hp-2")
        out2 = HyperparameterTuningNode().run(ctx2)

        model1 = json.loads(store.artifact_path(out1.artifacts[0]).read_text())
        model2 = json.loads(store.artifact_path(out2.artifacts[0]).read_text())

        self.assertEqual(
            model1["training"]["hyperparameter_tuning"]["best_params"],
            model2["training"]["hyperparameter_tuning"]["best_params"],
        )
        self.assertEqual(
            model1["training"]["hyperparameter_tuning"]["best_score"],
            model2["training"]["hyperparameter_tuning"]["best_score"],
        )


class HyperparameterTuningGBDTTests(unittest.TestCase):

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
        self.assertEqual(model["model_family"], "gbdt")
        self.assertIn("hyperparameter_tuning", model["training"])
        self.assertIn("best_score", model["training"]["hyperparameter_tuning"])
        self.assertGreater(model["training"]["hyperparameter_tuning"]["best_score"], 0)


class HyperparameterTuningApplyTests(unittest.TestCase):

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

        self.assertEqual(len(apply_output.artifacts), 1)
        scored_df = pl.read_parquet(store.artifact_path(apply_output.artifacts[0]))
        self.assertIn("predicted_bad_probability", scored_df.columns)
        for p in scored_df["predicted_bad_probability"]:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

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


if __name__ == "__main__":
    unittest.main()
