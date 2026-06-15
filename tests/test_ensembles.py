"""Tests for Phase 10 ensemble nodes: voting, weighted, and stacking."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.modeling.schema import validate_model_artifact
from cardre.nodes.ensembles import (
    StackingEnsembleNode,
    VotingEnsembleNode,
    WeightedEnsembleNode,
)
from cardre.nodes.ml_models import (
    DecisionTreeNode,
    GradientBoostingClassifierNode,
    RandomForestClassifierNode,
)
from cardre.store import ProjectStore


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
    rng = np.random.RandomState(seed)
    feat_a = rng.randn(n_rows) * 10 + 50
    feat_b = rng.randn(n_rows) * 5 + 20
    feat_c = rng.randn(n_rows) * 2 + 10
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

    from cardre.artifacts import write_json_artifact, write_parquet_artifact
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


def fit_two_models(store, data_art, def_art):
    """Fit a decision tree and GBDT, return their model artifacts."""
    from cardre.artifacts import write_json_artifact
    from cardre.modeling.serialization import write_estimator_artifact

    df = pl.read_parquet(store.artifact_path(data_art))
    features = ["feat_a", "feat_b", "feat_c"]
    X = df.select(features).to_numpy()
    y_raw = df["target"].cast(pl.String).to_list()
    y = np.array([1 if v == "bad" else 0 for v in y_raw])

    # Fit decision tree
    from sklearn.tree import DecisionTreeClassifier
    dt = DecisionTreeClassifier(max_depth=3, min_samples_leaf=5, random_state=42)
    dt.fit(X, y)

    dt_buf = __import__("io").BytesIO()
    __import__("joblib").dump(dt, dt_buf)
    dt_est_art = write_estimator_artifact(
        store, estimator_bytes=dt_buf.getvalue(), estimator_format="joblib",
        stem="dt-est", creating_run_id="test-run", creating_run_step_id="dt-fit",
        metadata={},
    )
    dt_model = {
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "decision_tree",
        "target_column": "target",
        "features": features,
        "class_mapping": {"0": "good", "1": "bad"},
        "bad_class_label": "bad",
        "target_event_value": "bad",
        "probability_column_index": 1,
        "feature_order_hash": json_logical_hash({"features": features}),
        "estimator_reference": {
            "artifact_id": dt_est_art.artifact_id,
            "logical_hash": dt_est_art.logical_hash,
            "physical_hash": dt_est_art.physical_hash,
            "estimator_format": "joblib",
        },
        "training": {"row_count": df.height, "params": {}, "elapsed_seconds": 0},
        "interpretability": {"explanation_type": "tree", "limitations": []},
        "warnings": [],
    }
    dt_art = write_json_artifact(
        store, artifact_type="model", role="model", stem="dt-model",
        payload=dt_model, metadata={"model_family": "decision_tree"},
    )

    # Fit GBDT
    from sklearn.ensemble import GradientBoostingClassifier
    gb = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
    gb.fit(X, y)

    gb_buf = __import__("io").BytesIO()
    __import__("joblib").dump(gb, gb_buf)
    gb_est_art = write_estimator_artifact(
        store, estimator_bytes=gb_buf.getvalue(), estimator_format="joblib",
        stem="gb-est", creating_run_id="test-run", creating_run_step_id="gb-fit",
        metadata={},
    )
    gb_model = {
        "schema_version": "cardre.model_artifact.v1",
        "model_family": "gbdt",
        "target_column": "target",
        "features": features,
        "class_mapping": {"0": "good", "1": "bad"},
        "bad_class_label": "bad",
        "target_event_value": "bad",
        "probability_column_index": 1,
        "feature_order_hash": json_logical_hash({"features": features}),
        "estimator_reference": {
            "artifact_id": gb_est_art.artifact_id,
            "logical_hash": gb_est_art.logical_hash,
            "physical_hash": gb_est_art.physical_hash,
            "estimator_format": "joblib",
        },
        "training": {"row_count": df.height, "params": {}, "elapsed_seconds": 0},
        "interpretability": {"explanation_type": "tree", "limitations": []},
        "warnings": [],
    }
    gb_art = write_json_artifact(
        store, artifact_type="model", role="model", stem="gb-model",
        payload=gb_model, metadata={"model_family": "gbdt"},
    )

    return dt_art, gb_art, dt_model, gb_model


def make_ensemble_context(
    store: ProjectStore,
    data_art,
    def_art,
    node_type: str,
    model_artifact_ids: list[str],
    *,
    params: dict | None = None,
    step_id: str = "ensemble-step",
) -> ExecutionContext:
    merged = {"model_artifact_ids": model_artifact_ids}
    if params:
        merged.update(params)
    step_spec = StepSpec(
        step_id=step_id,
        node_type=node_type,
        node_version="1",
        category="fit",
        params=merged,
        params_hash=json_logical_hash(merged),
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
        input_artifacts=[data_art, def_art],
        validated_params=merged,
        runtime_metadata={},
    )


class TestVotingEnsembleNode(unittest.TestCase):
    def setUp(self):
        self.store, self.tmp = make_store()
        self.data_art, self.def_art, self.df = make_numeric_dataset(self.store)
        self.dt_art, self.gb_art, _, _ = fit_two_models(
            self.store, self.data_art, self.def_art,
        )

    def test_soft_voting(self):
        node = VotingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"voting": "soft"},
        )
        out = node.run(ctx)
        self.assertEqual(len(out.artifacts), 1)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        self.assertEqual(model["model_family"], "voting_ensemble")
        self.assertEqual(model["model_payload"]["voting"], "soft")
        self.assertEqual(len(model["model_payload"]["base_models"]), 2)

    def test_hard_voting(self):
        node = VotingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"voting": "hard", "threshold": 0.6},
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        self.assertEqual(model["model_payload"]["voting"], "hard")
        self.assertEqual(model["model_payload"]["threshold"], 0.6)

    def test_model_artifact_valid(self):
        node = VotingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        errs = validate_model_artifact(model)
        self.assertEqual(errs, [])

    def test_requires_at_least_two_models(self):
        node = VotingEnsembleNode()
        errors = node.validate_params({"model_artifact_ids": ["x"]})
        self.assertTrue(any("at least 2" in e for e in errors))

    def test_experimental_warning(self):
        node = VotingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        codes = [w["code"] for w in model["warnings"]]
        self.assertIn("EXPERIMENTAL_ENSEMBLE", codes)

    def test_interpretability_post_hoc_only(self):
        node = VotingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        self.assertEqual(model["interpretability"]["explanation_level"], "post_hoc_only")
        self.assertFalse(model["interpretability"]["native_importance_available"])


class TestWeightedEnsembleNode(unittest.TestCase):
    def setUp(self):
        self.store, self.tmp = make_store()
        self.data_art, self.def_art, self.df = make_numeric_dataset(self.store)
        self.dt_art, self.gb_art, _, _ = fit_two_models(
            self.store, self.data_art, self.def_art,
        )

    def test_user_defined_weights(self):
        node = WeightedEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"weights": [0.7, 0.3]},
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        self.assertAlmostEqual(model["model_payload"]["weights"][0], 0.7, places=4)
        self.assertAlmostEqual(model["model_payload"]["weights"][1], 0.3, places=4)

    def test_optimize_weights(self):
        node = WeightedEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"optimize_weights": True},
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        weights = model["model_payload"]["weights"]
        self.assertEqual(len(weights), 2)
        self.assertAlmostEqual(sum(weights), 1.0, places=4)

    def test_default_equal_weights(self):
        node = WeightedEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        weights = model["model_payload"]["weights"]
        self.assertAlmostEqual(weights[0], 0.5, places=4)
        self.assertAlmostEqual(weights[1], 0.5, places=4)

    def test_model_artifact_valid(self):
        node = WeightedEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        errs = validate_model_artifact(model)
        self.assertEqual(errs, [])

    def test_weights_must_sum_to_one(self):
        node = WeightedEnsembleNode()
        errors = node.validate_params({
            "model_artifact_ids": ["a", "b"],
            "weights": [0.8, 0.3],
        })
        self.assertTrue(any("sum to 1" in e for e in errors))


class TestStackingEnsembleNode(unittest.TestCase):
    def setUp(self):
        self.store, self.tmp = make_store()
        self.data_art, self.def_art, self.df = make_numeric_dataset(self.store)
        self.dt_art, self.gb_art, _, _ = fit_two_models(
            self.store, self.data_art, self.def_art,
        )

    def test_stacking_logistic_meta(self):
        node = StackingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"meta_learner": "logistic_regression", "n_folds": 3},
        )
        out = node.run(ctx)
        self.assertGreaterEqual(len(out.artifacts), 2)
        model_art = [a for a in out.artifacts if a.role == "model"][0]
        report_art = [a for a in out.artifacts if a.role == "report"][0]
        model = json.loads(self.store.artifact_path(model_art).read_text())
        report = json.loads(self.store.artifact_path(report_art).read_text())
        self.assertEqual(model["model_family"], "stacking_ensemble")
        self.assertEqual(model["model_payload"]["meta_learner"], "logistic_regression")
        self.assertEqual(report["ensemble_type"], "stacking")
        self.assertEqual(len(report["fold_assignments"]), 3)

    def test_stacking_tree_meta(self):
        node = StackingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"meta_learner": "decision_tree", "n_folds": 3},
        )
        out = node.run(ctx)
        model_art = [a for a in out.artifacts if a.role == "model"][0]
        model = json.loads(self.store.artifact_path(model_art).read_text())
        self.assertEqual(model["model_payload"]["meta_learner"], "decision_tree")

    def test_stacking_has_estimator_reference(self):
        node = StackingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"n_folds": 3},
        )
        out = node.run(ctx)
        model_art = [a for a in out.artifacts if a.role == "model"][0]
        model = json.loads(self.store.artifact_path(model_art).read_text())
        self.assertIn("estimator_reference", model)
        self.assertTrue(model["estimator_reference"]["trusted_load_required"])

    def test_stacking_has_lineage_report(self):
        node = StackingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"n_folds": 3},
        )
        out = node.run(ctx)
        report_art = [a for a in out.artifacts if a.role == "report"][0]
        report = json.loads(self.store.artifact_path(report_art).read_text())
        self.assertIn("fold_assignments", report)
        self.assertIn("base_model_artifacts", report)
        self.assertEqual(report["n_folds"], 3)

    def test_stacking_logistic_meta_weights(self):
        node = StackingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"meta_learner": "logistic_regression", "n_folds": 3},
        )
        out = node.run(ctx)
        model_art = [a for a in out.artifacts if a.role == "model"][0]
        model = json.loads(self.store.artifact_path(model_art).read_text())
        meta_weights = model["model_payload"]["meta_weights"]
        self.assertIn("decision_tree", meta_weights)
        self.assertIn("gbdt", meta_weights)

    def test_model_artifact_valid(self):
        node = StackingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"n_folds": 3},
        )
        out = node.run(ctx)
        model_art = [a for a in out.artifacts if a.role == "model"][0]
        model = json.loads(self.store.artifact_path(model_art).read_text())
        errs = validate_model_artifact(model)
        self.assertEqual(errs, [])

    def test_requires_minimum_two_models(self):
        node = StackingEnsembleNode()
        errors = node.validate_params({"model_artifact_ids": ["x"]})
        self.assertTrue(any("at least 2" in e for e in errors))

    def test_experimental_and_leakage_warnings(self):
        node = StackingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"n_folds": 3},
        )
        out = node.run(ctx)
        model_art = [a for a in out.artifacts if a.role == "model"][0]
        model = json.loads(self.store.artifact_path(model_art).read_text())
        codes = [w["code"] for w in model["warnings"]]
        self.assertIn("EXPERIMENTAL_ENSEMBLE", codes)
        self.assertIn("LEAKAGE_CONTROLLED", codes)


if __name__ == "__main__":
    unittest.main()
