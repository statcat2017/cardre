"""Tests for Phase 10 ensemble nodes: voting, weighted, and stacking."""

from __future__ import annotations

import json

import numpy as np
import polars as pl

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.modeling.schema import validate_model_artifact
from cardre.nodes.ensembles import (
    VotingEnsembleNode,
    WeightedEnsembleNode,
)
from cardre.store import ProjectStore

from tests.helpers import make_numeric_dataset, make_store
import pytest

pytestmark = pytest.mark.integration



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


class TestVotingEnsembleNode:
    @pytest.fixture(autouse=True)
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
        assert len(out.artifacts) == 1
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        assert model["model_family"] == "voting_ensemble"
        assert model["model_payload"]["voting"] == "soft"
        assert len(model["model_payload"]["base_models"]) == 2

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
        assert model["model_payload"]["voting"] == "hard"
        assert model["model_payload"]["threshold"] == 0.6

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
        assert errs == []

    def test_requires_at_least_two_models(self):
        node = VotingEnsembleNode()
        errors = node.validate_params({"model_artifact_ids": ["x"]})
        assert any("at least 2" in e for e in errors)

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
        assert "EXPERIMENTAL_ENSEMBLE" in codes

    def test_interpretability_post_hoc_only(self):
        node = VotingEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        assert model["interpretability"]["explanation_level"] == "post_hoc_only"
        assert not model["interpretability"]["native_importance_available"]


class TestWeightedEnsembleNode:
    @pytest.fixture(autouse=True)
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
        assert model["model_payload"]["weights"][0] == pytest.approx(0.7, abs=5e-5)
        assert model["model_payload"]["weights"][1] == pytest.approx(0.3, abs=5e-5)

    def test_optimize_weights(self):
        node = WeightedEnsembleNode()
        ctx = make_ensemble_context(
            self.store, self.data_art, self.def_art,
            node.node_type,
            [self.dt_art.artifact_id, self.gb_art.artifact_id],
            params={"optimize_weights": True, "allow_train_optimization": True},
        )
        out = node.run(ctx)
        model = json.loads(self.store.artifact_path(out.artifacts[0]).read_text())
        weights = model["model_payload"]["weights"]
        assert len(weights) == 2
        assert sum(weights) == pytest.approx(1.0, abs=5e-5)

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
        assert weights[0] == pytest.approx(0.5, abs=5e-5)
        assert weights[1] == pytest.approx(0.5, abs=5e-5)

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
        assert errs == []

    def test_weights_must_sum_to_one(self):
        node = WeightedEnsembleNode()
        errors = node.validate_params({
            "model_artifact_ids": ["a", "b"],
            "weights": [0.8, 0.3],
        })
        assert any("sum to 1" in e for e in errors)
