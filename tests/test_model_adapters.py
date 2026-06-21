"""Characterization tests for model family adapters.

Covers logistic regression (with/without scorecard), sklearn estimator
(predict_proba and predict-only), ensembles, unsupported families, and
missing features.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ArtifactRef, ExecutionContext, StepSpec, json_logical_hash
from cardre.evidence import SCHEMA_SCORE_SCALING
from cardre.modeling.adapters import apply_model
from cardre.store import ProjectStore

from tests.helpers import make_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_estimator_artifact(store, clf, step_id: str) -> ArtifactRef:
    """Persist a fitted sklearn estimator as an artifact."""
    import io as _io
    import joblib
    from cardre.modeling.serialization import write_estimator_artifact
    buf = _io.BytesIO()
    joblib.dump(clf, buf)
    return write_estimator_artifact(
        store, estimator_bytes=buf.getvalue(),
        estimator_format="joblib",
        stem=f"estimator-{step_id}",
        creating_run_id="r1", creating_run_step_id=step_id,
        metadata={"model_family": "decision_tree"},
    )


def _make_train_artifact(store: ProjectStore, df: pl.DataFrame) -> ArtifactRef:
    return write_parquet_artifact(
        store, artifact_type="dataset", role="train",
        stem="train-data", frame=df,
        metadata={},
    )


def _make_scorecard_artifact(store: ProjectStore) -> tuple[ArtifactRef, dict]:
    data = {
        "offset": 500.0, "factor": 15.0,
        "higher_score_is_lower_risk": True,
    }
    art = write_json_artifact(
        store, artifact_type="scorecard", role="scorecard",
        stem="test-scorecard", payload=data,
        metadata={"schema_version": SCHEMA_SCORE_SCALING},
    )
    return art, data


def _make_model_artifact(store: ProjectStore, payload: dict) -> ArtifactRef:
    return write_json_artifact(
        store, artifact_type="model", role="model",
        stem="test-model", payload=payload,
        metadata={},
    )


def _execution_context(
    store: ProjectStore,
    input_artifacts: list[ArtifactRef],
    params: dict | None = None,
) -> ExecutionContext:
    spec = StepSpec(
        step_id="test-apply", node_type="cardre.apply_model",
        node_version="2", category="apply",
        params=params or {}, params_hash=json_logical_hash(params or {}),
        parent_step_ids=[], branch_label="", position=0,
    )
    return ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=input_artifacts,
        validated_params=params or {}, runtime_metadata={},
    )


_train_df = pl.DataFrame({
    "x1_woe": [0.2, -0.1, 0.5, -0.3],
    "x2_woe": [0.1, 0.3, -0.2, 0.0],
})


# ======================================================================
# Logistic regression
# ======================================================================


class TestLogisticAdapter:

    LOGISTIC_MODEL = {
        "model_family": "logistic_regression",
        "features": ["x1_woe", "x2_woe"],
        "intercept": -0.5,
        "coefficients": {"x1_woe": 0.8, "x2_woe": 0.3},
        "class_mapping": {"good": "0", "bad": "1"},
        "bad_class_label": "1",
        "target_event_value": "1",
        "probability_column_index": 1,
        "training": {"row_count": 100, "converged": True, "iterations": 10, "params": {}},
        "warnings": [],
    }

    def test_logistic_without_scorecard(self):
        store, tmp = make_store()
        store.initialize()
        train_art = _make_train_artifact(store, _train_df)
        model_art = _make_model_artifact(store, self.LOGISTIC_MODEL)

        ctx = _execution_context(store, [train_art, model_art])
        output = apply_model(ctx, self.LOGISTIC_MODEL, model_art)

        assert len(output.artifacts) >= 1
        scored = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        assert "predicted_bad_probability" in scored.columns
        assert "raw_model_output" in scored.columns
        assert scored.height == _train_df.height

    def test_logistic_with_scorecard(self):
        store, tmp = make_store()
        store.initialize()
        train_art = _make_train_artifact(store, _train_df)
        model_art = _make_model_artifact(store, self.LOGISTIC_MODEL)
        scorecard_art, scorecard_data = _make_scorecard_artifact(store)

        ctx = _execution_context(store, [train_art, model_art, scorecard_art])
        scorecard_artifact_id = scorecard_art.artifact_id
        _ = scorecard_data
        output = apply_model(
            ctx, self.LOGISTIC_MODEL, model_art,
            scorecard_parsed=scorecard_data,
            scorecard_artifact_id=scorecard_artifact_id,
        )

        assert len(output.artifacts) >= 1
        scored = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        assert "score" in scored.columns
        assert "cardre_scaled_score" in scored.columns


# ======================================================================
# Unsupported family
# ======================================================================


# ======================================================================
# Sklearn estimator (decision tree with predict_proba)
# ======================================================================


class TestSklearnEstimatorAdapter:

    def test_decision_tree_predict_proba(self):
        from sklearn.tree import DecisionTreeClassifier
        store, tmp = make_store()
        store.initialize()

        X = np.array([[0.2, 0.1], [-0.1, 0.3], [0.5, -0.2], [-0.3, 0.0]])
        y = np.array([1, 0, 1, 0])
        clf = DecisionTreeClassifier(max_depth=2, random_state=42)
        clf.fit(X, y)

        estimator_art = _write_estimator_artifact(store, clf, "dt")
        train_art = _make_train_artifact(store, _train_df)

        model = {
            "model_family": "decision_tree",
            "feature_contract": {"features": ["x1_woe", "x2_woe"]},
            "probability_column_index": 1,
            "estimator_reference": {
                "artifact_id": estimator_art.artifact_id,
                "logical_hash": estimator_art.logical_hash,
            },
        }
        model_art = _make_model_artifact(store, model)
        ctx = _execution_context(store, [train_art, model_art])

        output = apply_model(ctx, model, model_art)
        assert len(output.artifacts) >= 1
        scored = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        assert "predicted_bad_probability" in scored.columns
        assert scored.height == _train_df.height


# ======================================================================
# Ensemble (soft voting)
# ======================================================================


class TestEnsembleAdapter:

    def test_soft_voting_ensemble(self):
        from sklearn.tree import DecisionTreeClassifier
        store, tmp = make_store()
        store.initialize()

        # Fit two small trees as base models
        X = np.array([[0.2, 0.1], [-0.1, 0.3], [0.5, -0.2], [-0.3, 0.0]])
        y = np.array([1, 0, 1, 0])
        clf1 = DecisionTreeClassifier(max_depth=1, random_state=1)
        clf1.fit(X, y)
        clf2 = DecisionTreeClassifier(max_depth=1, random_state=2)
        clf2.fit(X, y)

        est_art1 = _write_estimator_artifact(store, clf1, "ens1")
        est_art2 = _write_estimator_artifact(store, clf2, "ens2")

        # Create base model artifacts (JSON model dicts that reference estimators)
        base1 = {
            "model_family": "decision_tree",
            "features": ["x1_woe", "x2_woe"],
            "feature_contract": {"features": ["x1_woe", "x2_woe"]},
            "probability_column_index": 1,
            "estimator_reference": {
                "artifact_id": est_art1.artifact_id,
                "logical_hash": est_art1.logical_hash,
            },
        }
        base2 = {
            "model_family": "decision_tree",
            "features": ["x1_woe", "x2_woe"],
            "feature_contract": {"features": ["x1_woe", "x2_woe"]},
            "probability_column_index": 1,
            "estimator_reference": {
                "artifact_id": est_art2.artifact_id,
                "logical_hash": est_art2.logical_hash,
            },
        }
        bm1_art = _make_model_artifact(store, base1)
        bm2_art = _make_model_artifact(store, base2)

        train_art = _make_train_artifact(store, _train_df)

        model = {
            "model_family": "voting_ensemble",
            "features": ["x1_woe", "x2_woe"],
            "probability_column_index": 1,
            "model_payload": {
                "ensemble_type": "voting",
                "voting": "soft",
                "threshold": 0.5,
                "base_models": [
                    {"artifact_id": bm1_art.artifact_id},
                    {"artifact_id": bm2_art.artifact_id},
                ],
            },
        }
        model_art = _make_model_artifact(store, model)

        # Pre-parse base models and attach as _base_models_parsed (same
        # pattern ApplyModelNode.run() uses before calling the adapter).
        base_parsed = [dict(base1), dict(base2)]
        model["_base_models_parsed"] = base_parsed

        ctx = _execution_context(store, [train_art, model_art])
        output = apply_model(ctx, model, model_art)
        assert len(output.artifacts) >= 1
        scored = pl.read_parquet(store.artifact_path(output.artifacts[0]))
        assert "predicted_bad_probability" in scored.columns
        assert scored.height == _train_df.height


# ======================================================================
# Unsupported family
# ======================================================================


class TestUnsupportedFamily:

    def test_raises_on_unknown_family(self):
        store, tmp = make_store()
        store.initialize()
        train_art = _make_train_artifact(store, _train_df)
        model = {"model_family": "nonexistent", "features": []}
        model_art = _make_model_artifact(store, model)
        ctx = _execution_context(store, [train_art, model_art])

        with pytest.raises(ValueError, match="unsupported model_family"):
            apply_model(ctx, model, model_art)

    def test_raises_on_missing_features(self):
        store, tmp = make_store()
        store.initialize()
        train_art = _make_train_artifact(store, _train_df)
        model = dict(TestLogisticAdapter.LOGISTIC_MODEL)
        model["features"] = ["x1_woe", "missing_col"]
        model_art = _make_model_artifact(store, model)
        ctx = _execution_context(store, [train_art, model_art])

        with pytest.raises(ValueError, match="missing features"):
            apply_model(ctx, model, model_art)
