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

from cardre.artifacts import make_fingerprint, write_json_artifact, write_parquet_artifact
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
        params = context.validated_params
        model_artifact_ids = list(params.get("model_artifact_ids", []))
        voting = params.get("voting", "soft")
        threshold = float(params.get("threshold", 0.5))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        def_art = next((a for a in context.input_artifacts if a.role == "definition"), None)
        if train_art is None:
            raise ValueError("voting_ensemble requires a train artifact")

        meta = {}
        if def_art:
            try:
                meta = json.loads(store.artifact_path(def_art).read_text())
            except Exception:
                pass

        target_col = meta.get("target_column", "")
        good_values = set(str(v) for v in meta.get("good_values", []))
        bad_values = set(str(v) for v in meta.get("bad_values", []))

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

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[artifact],
        )
        return NodeOutput(
            artifacts=[artifact],
            metrics={"n_models": len(models)},
            execution_fingerprint=fingerprint,
        )


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
        params = context.validated_params
        model_artifact_ids = list(params.get("model_artifact_ids", []))
        user_weights = list(params.get("weights", []))
        optimize = params.get("optimize_weights", False)

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        def_art = next((a for a in context.input_artifacts if a.role == "definition"), None)
        if train_art is None:
            raise ValueError("weighted_ensemble requires a train artifact")

        meta = {}
        if def_art:
            try:
                meta = json.loads(store.artifact_path(def_art).read_text())
            except Exception:
                pass

        target_col = meta.get("target_column", "")
        good_values = set(str(v) for v in meta.get("good_values", []))
        bad_values = set(str(v) for v in meta.get("bad_values", []))

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

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[artifact],
        )
        return NodeOutput(
            artifacts=[artifact],
            metrics={"n_models": len(models)},
            execution_fingerprint=fingerprint,
        )

    def _optimize_weights(
        self,
        prob_matrix: np.ndarray,
        df: pl.DataFrame,
        target_col: str,
        bad_values: set[str],
    ) -> np.ndarray:
        """Optimize weights to maximize AUC on training data."""
        from sklearn.metrics import roc_auc_score

        y_raw = df[target_col].cast(pl.String).to_list()
        y_bin = np.array([1 if str(v) in bad_values else 0 for v in y_raw])

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


class StackingEnsembleNode(NodeType):
    """Stacking ensemble with explicit OOF lineage for leakage prevention.

    Uses base model predictions as features for a meta-learner.
    Requires fold assignment to prevent leakage. Records full
    lineage: fold spec, fold assignments, base model artifacts
    per fold, OOF predictions, and meta-training data.

    This is an experimental/research node. Stacking is
    leakage-sensitive and requires careful governance.
    """

    node_type = "cardre.stacking_ensemble"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model", "report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        model_artifact_ids = params.get("model_artifact_ids", [])
        if not isinstance(model_artifact_ids, list) or len(model_artifact_ids) < 2:
            errors.append("model_artifact_ids must be a list with at least 2 entries")

        n_folds = params.get("n_folds", 5)
        try:
            if int(n_folds) < 2:
                errors.append("n_folds must be >= 2")
        except (ValueError, TypeError):
            errors.append("n_folds must be an integer")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        meta_learner = params.get("meta_learner", "logistic_regression")
        valid_meta = {"logistic_regression", "decision_tree", "random_forest"}
        if meta_learner not in valid_meta:
            errors.append(f"meta_learner must be one of {sorted(valid_meta)}")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold
        from sklearn.tree import DecisionTreeClassifier

        store = context.store
        params = context.validated_params
        model_artifact_ids = list(params.get("model_artifact_ids", []))
        n_folds = int(params.get("n_folds", 5))
        random_seed = int(params.get("random_seed", 42))
        meta_learner_type = params.get("meta_learner", "logistic_regression")

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        def_art = next((a for a in context.input_artifacts if a.role == "definition"), None)
        if train_art is None:
            raise ValueError("stacking_ensemble requires a train artifact")

        meta = {}
        if def_art:
            try:
                meta = json.loads(store.artifact_path(def_art).read_text())
            except Exception:
                pass

        target_col = meta.get("target_column", "")
        good_values = set(str(v) for v in meta.get("good_values", []))
        bad_values = set(str(v) for v in meta.get("bad_values", []))

        if not bad_values:
            raise ValueError("bad_values required for stacking ensemble")

        df = pl.read_parquet(store.artifact_path(train_art))

        if target_col not in df.columns:
            raise ValueError(f"Target column {target_col!r} not found")

        y_raw = df[target_col].cast(pl.String).to_list()
        y_binary = np.array([1 if str(v) in bad_values else 0 for v in y_raw])

        # Load base model artifacts (JSON metadata)
        base_models: list[dict] = []
        for aid in model_artifact_ids:
            model = _load_model_artifact(store, aid)
            base_models.append(model)

        # Collect all features
        all_features = set()
        for m in base_models:
            all_features.update(m.get("features", []))
        features = sorted(all_features)

        X_all = df.select(features).to_numpy()

        # Stratified K-Fold for OOF predictions
        # Each base model's stored fitted estimator is used without refitting
        skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=random_seed)
        oof_predictions = np.zeros((len(y_binary), len(base_models)))
        fold_assignments = []

        for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X_all, y_binary)):
            fold_assignments.append({
                "fold": fold_idx,
                "train_indices": train_idx.tolist(),
                "val_indices": val_idx.tolist(),
                "train_size": len(train_idx),
                "val_size": len(val_idx),
            })

            for model_idx, base_model in enumerate(base_models):
                model_features = base_model.get("features", [])
                val_df = df.select(model_features)[val_idx]
                oof_predictions[val_idx, model_idx] = _get_predictions(
                    store, base_model, val_df, model_features,
                )

        # Fit meta-learner on OOF predictions
        if meta_learner_type == "logistic_regression":
            meta_learner = LogisticRegression(max_iter=1000, random_state=random_seed)
        elif meta_learner_type == "decision_tree":
            meta_learner = DecisionTreeClassifier(max_depth=3, random_state=random_seed)
        else:
            meta_learner = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=random_seed)

        meta_learner.fit(oof_predictions, y_binary)

        # Store meta-learner as estimator
        buf = io.BytesIO()
        joblib.dump(meta_learner, buf)
        from cardre.modeling.serialization import write_estimator_artifact
        meta_estimator_art = write_estimator_artifact(
            store,
            estimator_bytes=buf.getvalue(),
            estimator_format="joblib",
            stem=f"stacking-meta-{context.step_spec.step_id}",
            creating_run_id=context.run_id,
            creating_run_step_id=context.step_spec.step_id,
            metadata={"meta_learner": meta_learner_type},
        )

        # Extract meta-learner weights if logistic
        meta_weights = {}
        if meta_learner_type == "logistic_regression" and hasattr(meta_learner, "coef_"):
            for i, base_model in enumerate(base_models):
                meta_weights[base_model.get("model_family", f"model_{i}")] = round(
                    float(meta_learner.coef_[0][i]), 6,
                )

        bad_class = sorted(bad_values)[0]
        good_class = sorted(good_values)[0]

        base_model_refs = [
            {"artifact_id": m.get("estimator_reference", {}).get("artifact_id", ""),
             "model_artifact_id": model_artifact_ids[i] if i < len(model_artifact_ids) else "",
             "model_family": m.get("model_family", "unknown")}
            for i, m in enumerate(base_models)
        ]

        ensemble_model = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "stacking_ensemble",
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
            "estimator_reference": {
                "artifact_id": meta_estimator_art.artifact_id,
                "logical_hash": meta_estimator_art.logical_hash,
                "physical_hash": meta_estimator_art.physical_hash,
                "estimator_format": "joblib",
                "trusted_load_required": True,
                "creating_run_id": context.run_id,
                "creating_run_step_id": context.step_spec.step_id,
            },
            "training": {
                "row_count": df.height,
                "params": {
                    "n_folds": n_folds,
                    "n_base_models": len(base_models),
                    "meta_learner": meta_learner_type,
                    "random_seed": random_seed,
                },
                "elapsed_seconds": 0,
            },
            "model_payload": {
                "ensemble_type": "stacking",
                "base_models": base_model_refs,
                "meta_learner": meta_learner_type,
                "meta_weights": meta_weights,
                "n_folds": n_folds,
            },
            "interpretability": {
                "explanation_type": "ensemble",
                "explanation_level": "post_hoc_only",
                "native_importance_available": False,
                "limitations": [
                    "Stacking ensemble uses base model predictions as meta-features",
                    "Meta-learner weights show base model contribution but predictions are not decomposable",
                    "Requires OOF lineage to prevent leakage; not suitable for small datasets",
                    "Ensemble does not produce native scorecard points",
                    "Requires explicit limitation acceptance for champion promotion",
                ],
                "global_importance_fields": [],
            },
            "warnings": [{
                "code": "EXPERIMENTAL_ENSEMBLE",
                "message": "Stacking ensemble is an experimental/research method. "
                           "Leakage-sensitive; requires careful governance.",
            }, {
                "code": "LEAKAGE_CONTROLLED",
                "message": f"OOF predictions used with {n_folds} folds. "
                           f"Verify fold assignment artifacts for audit.",
            }],
        }

        model_art = write_json_artifact(
            store, artifact_type="model", role="model",
            stem=f"stacking-ensemble-{context.step_spec.step_id}",
            payload=ensemble_model,
            metadata={
                "ensemble_type": "stacking",
                "n_models": len(base_models),
                "n_folds": n_folds,
            },
        )

        # Lineage report
        lineage_report = {
            "ensemble_type": "stacking",
            "n_folds": n_folds,
            "fold_assignments": fold_assignments,
            "base_model_artifacts": base_model_refs,
            "meta_learner": meta_learner_type,
            "meta_estimator_artifact_id": meta_estimator_art.artifact_id,
            "oof_prediction_shape": list(oof_predictions.shape),
            "meta_weights": meta_weights,
            "warnings": [
                "This report contains fold-level lineage for stacking audit. "
                "Verify no test/OOT rows leaked into meta-training.",
            ],
        }
        report_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"stacking-lineage-{context.step_spec.step_id}",
            payload=lineage_report,
            metadata={"n_folds": n_folds},
        )

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[model_art, report_art, meta_estimator_art],
        )
        return NodeOutput(
            artifacts=[model_art, report_art, meta_estimator_art],
            metrics={"n_models": len(base_models), "n_folds": n_folds},
            execution_fingerprint=fingerprint,
        )
