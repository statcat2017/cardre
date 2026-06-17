"""Advanced ensemble nodes — voting, weighted, and stacking.

Phase 10 adds research-level ensemble methods. These are advanced
challengers hidden from default governed templates. All ensemble
nodes consume explicitly selected fitted model artifact IDs and
record full lineage for auditability.
"""

from __future__ import annotations

import io
import json
import time
from typing import Any

import joblib
import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    json_logical_hash,
)


def _load_estimator(store, estimator_ref: dict):
    """Load a fitted estimator from an estimator reference."""
    artifact_id = estimator_ref.get("artifact_id", "")
    if not artifact_id:
        raise ValueError("estimator_reference.artifact_id is required")

    from cardre.modeling.serialization import read_estimator_artifact
    art = store.get_artifact(artifact_id)
    if art is None:
        raise ValueError(f"Estimator artifact {artifact_id!r} not found")

    estimator_bytes = read_estimator_artifact(
        store, art,
        expected_logical_hash=estimator_ref.get("logical_hash"),
    )
    return joblib.load(io.BytesIO(estimator_bytes))


def _load_model_artifact(store, artifact_id: str) -> dict:
    """Load a model JSON artifact by ID."""
    art = store.get_artifact(artifact_id)
    if art is None:
        raise ValueError(f"Model artifact {artifact_id!r} not found")
    return json.loads(store.artifact_path(art).read_text())


def _get_predictions(
    store, model: dict, df: pl.DataFrame, features: list[str],
) -> np.ndarray:
    """Get probability predictions from a model artifact on a dataframe."""
    model_family = model.get("model_family", "")
    prob_col_idx = model.get("probability_column_index", 1)

    if model_family == "logistic_regression":
        coefs = model.get("coefficients", {})
        intercept = float(model.get("intercept", 0))
        X = df.select(features).to_numpy()
        log_odds = np.full(X.shape[0], intercept, dtype=np.float64)
        for i, feat in enumerate(features):
            log_odds += float(coefs.get(feat, 0)) * X[:, i]
        return 1.0 / (1.0 + np.exp(-log_odds))
    else:
        estimator_ref = model.get("estimator_reference", {})
        estimator = _load_estimator(store, estimator_ref)
        X = df.select(features).to_numpy()
        if hasattr(estimator, "predict_proba"):
            proba = estimator.predict_proba(X)
            if proba.shape[1] > prob_col_idx:
                return proba[:, prob_col_idx]
            return proba[:, -1]
        return estimator.predict(X).astype(np.float64)


class VotingEnsembleNode(NodeType):
    """Hard or soft voting ensemble across fitted model artifacts.

    Consumes explicitly selected model artifact IDs. Hard voting uses
    majority rule on predicted labels. Soft voting averages predicted
    probabilities.

    This is an experimental/research node hidden from default governed
    templates.
    """

    node_type = "cardre.voting_ensemble"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        model_artifact_ids = params.get("model_artifact_ids", [])
        if not isinstance(model_artifact_ids, list) or len(model_artifact_ids) < 2:
            errors.append("model_artifact_ids must be a list with at least 2 entries")

        voting = params.get("voting", "soft")
        if voting not in ("hard", "soft"):
            errors.append("voting must be 'hard' or 'soft'")

        threshold = params.get("threshold", 0.5)
        try:
            v = float(threshold)
            if v < 0 or v > 1:
                errors.append("threshold must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("threshold must be a number")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        model_artifact_ids = list(params.get("model_artifact_ids", []))
        voting = params.get("voting", "soft")
        threshold = float(params.get("threshold", 0.5))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        if train_art is None:
            raise ValueError("voting_ensemble requires a train artifact")

        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta else ""
        good_values = set(str(v) for v in (meta.good_values if meta else []))
        bad_values = set(str(v) for v in (meta.bad_values if meta else []))

        if not bad_values:
            raise ValueError("bad_values required for voting ensemble")

        df = pl.read_parquet(store.artifact_path(train_art))

        # Load all models and get predictions
        models: list[dict] = []
        model_refs: list[dict] = []
        for aid in model_artifact_ids:
            model = _load_model_artifact(store, aid)
            models.append(model)
            model_refs.append({
                "artifact_id": aid,
                "model_family": model.get("model_family", "unknown"),
                "features": model.get("features", []),
            })

        # Use intersection of all feature sets
        all_features = set()
        for m in models:
            all_features.update(m.get("features", []))
        features = sorted(all_features)

        # Get predictions from each model
        all_probs: list[np.ndarray] = []
        for model in models:
            model_features = model.get("features", [])
            missing = [f for f in model_features if f not in df.columns]
            if missing:
                raise ValueError(f"Model {model.get('model_family')} missing features: {missing}")
            probs = _get_predictions(store, model, df, model_features)
            all_probs.append(probs)

        prob_matrix = np.column_stack(all_probs)

        if voting == "soft":
            # Average probabilities
            ensemble_probs = np.mean(prob_matrix, axis=1)
        else:
            # Hard voting: majority of thresholded predictions
            predictions = (prob_matrix >= threshold).astype(int)
            majority = np.sum(predictions, axis=1) > (len(models) / 2)
            ensemble_probs = majority.astype(float)

        # Build ensemble model artifact
        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        ensemble_model = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "voting_ensemble",
            "target_column": target_col,
            "features": features,
            "class_mapping": {"0": str(good_class), "1": str(bad_class)},
            "bad_class_label": str(bad_class),
            "target_event_value": str(bad_class),
            "probability_column_index": 1,
            "feature_order_hash": json_logical_hash({"features": features}),
            "feature_strategy": "ensemble",
            "feature_contract": {
                "features": features,
                "transformation_strategy": "ensemble",
            },
            "training": {
                "row_count": df.height,
                "params": {
                    "voting": voting,
                    "threshold": threshold,
                    "n_models": len(models),
                },
                "elapsed_seconds": 0,
            },
            "model_payload": {
                "ensemble_type": "voting",
                "voting": voting,
                "threshold": threshold,
                "base_models": model_refs,
            },
            "interpretability": {
                "explanation_type": "ensemble",
                "explanation_level": "post_hoc_only",
                "native_importance_available": False,
                "limitations": [
                    "Voting ensemble is a black-box combiner: individual model "
                    "contributions are not decomposable per prediction",
                    "Ensemble does not produce native scorecard points",
                    "Requires explicit limitation acceptance for champion promotion",
                ],
                "global_importance_fields": [],
            },
            "warnings": [{
                "code": "EXPERIMENTAL_ENSEMBLE",
                "message": "Voting ensemble is an experimental/research method. "
                           "Not recommended for governed scorecard production.",
            }],
        }

        artifact = write_json_artifact(
            store, artifact_type="model", role="model",
            stem=f"voting-ensemble-{context.step_spec.step_id}",
            payload=ensemble_model,
            metadata={
                "ensemble_type": "voting",
                "n_models": len(models),
                "voting": voting,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"n_models": len(models)})


class WeightedEnsembleNode(NodeType):
    """Weighted ensemble with user-defined or validation-optimized weights.

    Consumes explicitly selected model artifact IDs and corresponding
    weights. Can optimize weights on a validation split.

    This is an experimental/research node hidden from default governed
    templates.
    """

    node_type = "cardre.weighted_ensemble"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        model_artifact_ids = params.get("model_artifact_ids", [])
        if not isinstance(model_artifact_ids, list) or len(model_artifact_ids) < 2:
            errors.append("model_artifact_ids must be a list with at least 2 entries")

        weights = params.get("weights", [])
        if weights and len(weights) != len(model_artifact_ids):
            errors.append("weights length must match model_artifact_ids length")

        if weights:
            total = sum(weights)
            if abs(total - 1.0) > 0.01:
                errors.append(f"weights must sum to 1.0 (got {total:.4f})")

        optimize_weights = params.get("optimize_weights", False)
        if not isinstance(optimize_weights, bool):
            errors.append("optimize_weights must be a boolean")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        model_artifact_ids = list(params.get("model_artifact_ids", []))
        user_weights = list(params.get("weights", []))
        optimize = params.get("optimize_weights", False)

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        if train_art is None:
            raise ValueError("weighted_ensemble requires a train artifact")

        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta else ""
        good_values = set(str(v) for v in (meta.good_values if meta else []))
        bad_values = set(str(v) for v in (meta.bad_values if meta else []))

        if not bad_values:
            raise ValueError("bad_values required for weighted ensemble")

        df = pl.read_parquet(store.artifact_path(train_art))

        # Load models
        models: list[dict] = []
        model_refs: list[dict] = []
        for aid in model_artifact_ids:
            model = _load_model_artifact(store, aid)
            models.append(model)
            model_refs.append({
                "artifact_id": aid,
                "model_family": model.get("model_family", "unknown"),
                "features": model.get("features", []),
            })

        # Get predictions
        all_probs: list[np.ndarray] = []
        for model in models:
            model_features = model.get("features", [])
            probs = _get_predictions(store, model, df, model_features)
            all_probs.append(probs)

        prob_matrix = np.column_stack(all_probs)

        # Determine weights
        if user_weights and not optimize:
            weights = np.array(user_weights, dtype=np.float64)
        elif optimize:
            weights = self._optimize_weights(prob_matrix, df, target_col, bad_values)
        else:
            weights = np.ones(len(models)) / len(models)

        # Weighted average
        ensemble_probs = prob_matrix @ weights

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        all_features = set()
        for m in models:
            all_features.update(m.get("features", []))
        features = sorted(all_features)

        ensemble_model = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "weighted_ensemble",
            "target_column": target_col,
            "features": features,
            "class_mapping": {"0": str(good_class), "1": str(bad_class)},
            "bad_class_label": str(bad_class),
            "target_event_value": str(bad_class),
            "probability_column_index": 1,
            "feature_order_hash": json_logical_hash({"features": features}),
            "feature_strategy": "ensemble",
            "feature_contract": {
                "features": features,
                "transformation_strategy": "ensemble",
            },
            "training": {
                "row_count": df.height,
                "params": {
                    "weights": weights.tolist(),
                    "optimize_weights": optimize,
                    "n_models": len(models),
                },
                "elapsed_seconds": 0,
            },
            "model_payload": {
                "ensemble_type": "weighted",
                "weights": weights.tolist(),
                "optimize_weights": optimize,
                "base_models": model_refs,
            },
            "interpretability": {
                "explanation_type": "ensemble",
                "explanation_level": "post_hoc_only",
                "native_importance_available": False,
                "limitations": [
                    "Weighted ensemble combines models with fixed or optimized weights",
                    "Weight contributions are visible but individual predictions are not decomposable",
                    "Ensemble does not produce native scorecard points",
                    "Requires explicit limitation acceptance for champion promotion",
                ],
                "global_importance_fields": [],
            },
            "warnings": [{
                "code": "EXPERIMENTAL_ENSEMBLE",
                "message": "Weighted ensemble is an experimental/research method. "
                           "Not recommended for governed scorecard production.",
            }],
        }

        artifact = write_json_artifact(
            store, artifact_type="model", role="model",
            stem=f"weighted-ensemble-{context.step_spec.step_id}",
            payload=ensemble_model,
            metadata={
                "ensemble_type": "weighted",
                "n_models": len(models),
                "weights": weights.tolist(),
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"n_models": len(models)})

    def _optimize_weights(
        self,
        prob_matrix: np.ndarray,
        df: pl.DataFrame,
        target_col: str,
        bad_values: set[str],
    ) -> np.ndarray:
        """Optimize weights to maximize AUC on training data."""
        from sklearn.metrics import roc_auc_score

        y_bin = df[target_col].cast(pl.String).is_in(bad_values).cast(pl.Int64).to_numpy()

        n_models = prob_matrix.shape[1]
        best_weights = np.ones(n_models) / n_models
        best_auc = 0.0

        # Grid search over weight space
        rng = np.random.RandomState(42)
        for _ in range(500):
            w = rng.dirichlet(np.ones(n_models))
            ensemble = prob_matrix @ w
            try:
                auc = roc_auc_score(y_bin, ensemble)
                if auc > best_auc:
                    best_auc = auc
                    best_weights = w.copy()
            except ValueError:
                continue

        return best_weights

# StackingEnsembleNode is deferred until fold-level base-model artifacts and
# leakage-safe lineage semantics are implemented. The class and apply dispatch
# were removed to avoid advertising a known-bad path. See PR #24 review for details.
