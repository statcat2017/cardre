"""Model family adapters for applying fitted models to score datasets.

Replaces the model-family conditional dispatch in ``ApplyModelNode``
with a pluggable adapter interface.
"""

from __future__ import annotations

import io
import json
from typing import Any, Protocol

import joblib
import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ArtifactRef, ExecutionContext, JsonDict, NodeOutput
from cardre.evidence import SCHEMA_SCORE_APPLICATION_EVIDENCE
from cardre.modeling.serialization import read_estimator_artifact
from cardre.store import ProjectStore


class ModelApplyAdapter(Protocol):
    """Interface for applying a fitted model to score datasets."""

    model_family: str

    def apply(
        self,
        context: ExecutionContext,
        model: dict[str, Any],
        model_art: ArtifactRef,
        scorecard_art: ArtifactRef | None = None,
        bundle_art: ArtifactRef | None = None,
    ) -> NodeOutput:
        ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DATA_ROLES = ("train", "test", "oot")


def _build_evidence(
    roles_evidence: dict[str, JsonDict],
    model_art: ArtifactRef,
    scorecard_art: ArtifactRef | None,
    bundle_art: ArtifactRef | None,
) -> JsonDict:
    evidence: JsonDict = {
        "schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE,
        "model_artifact_id": model_art.artifact_id,
        "roles": roles_evidence,
        "warnings": [],
    }
    if bundle_art is not None:
        evidence["frozen_bundle_artifact_id"] = bundle_art.artifact_id
    if scorecard_art is not None:
        evidence["scorecard_artifact_id"] = scorecard_art.artifact_id
    return evidence


def _write_evidence_artifact(
    store: ProjectStore,
    evidence: JsonDict,
    step_id: str,
) -> ArtifactRef:
    return write_json_artifact(
        store, artifact_type="report", role="report",
        stem=f"score-apply-evidence-{step_id}",
        payload=evidence,
        metadata={"schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE},
    )


# ---------------------------------------------------------------------------
# Logistic regression adapter
# ---------------------------------------------------------------------------


def _apply_logistic_model(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_art: ArtifactRef | None = None,
    bundle_art: ArtifactRef | None = None,
) -> NodeOutput:
    store = context.store

    features = model.get("features", [])
    intercept = float(model.get("intercept", 0))
    coefficients = model.get("coefficients", {})

    if scorecard_art is not None:
        scorecard = json.loads(store.artifact_path(scorecard_art).read_text())
        offset = float(scorecard.get("offset", 0))
        factor_val = float(scorecard.get("factor", 1))
        direction = -1.0 if scorecard.get("higher_score_is_lower_risk", True) else 1.0
        has_scorecard = True
    else:
        offset = 0.0
        factor_val = 1.0
        direction = -1.0
        has_scorecard = False

    data_arts = [a for a in context.input_artifacts if a.role in _DATA_ROLES]
    outputs: list[ArtifactRef] = []
    roles_evidence: dict[str, JsonDict] = {}

    for data_art in data_arts:
        df = pl.read_parquet(store.artifact_path(data_art))
        role = data_art.role
        missing = [f for f in features if f not in df.columns]
        if missing:
            raise ValueError(f"apply_model: role {role!r} missing features {missing}")

        log_odds_expr = pl.lit(intercept)
        for feat in features:
            coef = float(coefficients.get(feat, 0))
            log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(coef)

        prob_expr = (1.0 / (1.0 + (-log_odds_expr).exp())).alias("predicted_bad_probability")
        raw_expr = log_odds_expr.alias("raw_model_output")

        base_metadata: JsonDict = {
            "model_artifact_id": model_art.artifact_id,
            "model_family": "logistic_regression",
        }
        if scorecard_art is not None:
            base_metadata["scorecard_artifact_id"] = scorecard_art.artifact_id
        if bundle_art is not None:
            base_metadata["frozen_bundle_artifact_id"] = bundle_art.artifact_id

        output_cols = ["predicted_bad_probability", "raw_model_output",
                       "model_artifact_id", "model_family"]
        add_exprs = [
            prob_expr, raw_expr,
            pl.lit(model_art.artifact_id).alias("model_artifact_id"),
            pl.lit("logistic_regression").alias("model_family"),
        ]

        if has_scorecard:
            score_expr = pl.lit(offset) + pl.lit(direction * factor_val) * log_odds_expr
            add_exprs.append(score_expr.alias("score"))
            add_exprs.append(score_expr.alias("cardre_scaled_score"))
            output_cols.extend(["score", "cardre_scaled_score"])

        df = df.with_columns(add_exprs)
        art = write_parquet_artifact(
            store, artifact_type="dataset", role=role,
            stem=f"scored-{role}-{context.step_spec.step_id}",
            frame=df, metadata=base_metadata,
        )
        outputs.append(art)

        pd_series = df["predicted_bad_probability"]
        role_entry: JsonDict = {
            "source_artifact_id": data_art.artifact_id,
            "output_artifact_id": art.artifact_id,
            "row_count": df.height,
            "required_features": features,
            "missing_features": missing,
            "output_columns": output_cols,
            "pd_min": round(float(pd_series.min()), 6),
            "pd_max": round(float(pd_series.max()), 6),
            "pd_mean": round(float(pd_series.mean()), 6),
        }
        if has_scorecard and "score" in df.columns:
            score_series = df["score"]
            role_entry["score_min"] = round(float(score_series.min()), 2)
            role_entry["score_max"] = round(float(score_series.max()), 2)
            role_entry["score_mean"] = round(float(score_series.mean()), 2)
        roles_evidence[role] = role_entry

    evidence = _build_evidence(roles_evidence, model_art, scorecard_art, bundle_art)
    evidence_art = _write_evidence_artifact(store, evidence, context.step_spec.step_id)

    return NodeOutput(
        artifacts=outputs + [evidence_art],
        metrics={"output_count": len(outputs)},
    )


# ---------------------------------------------------------------------------
# Sklearn estimator adapter (decision tree, RF, GBDT, XGBoost, LightGBM, CatBoost)
# ---------------------------------------------------------------------------


def _apply_sklearn_estimator(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_art: ArtifactRef | None = None,
    bundle_art: ArtifactRef | None = None,
) -> NodeOutput:
    store = context.store

    estimator_ref = model.get("estimator_reference", {})
    estimator_artifact_id = estimator_ref.get("artifact_id", "")

    feature_contract = model.get("feature_contract", {})
    features = feature_contract.get("features", [])
    if not features:
        features = model.get("features", [])

    prob_col_idx = model.get("probability_column_index", 1)

    scorecard = None
    if scorecard_art is not None:
        scorecard = json.loads(store.artifact_path(scorecard_art).read_text())

    if not estimator_artifact_id:
        raise ValueError(
            "apply_model: non-logistic model requires estimator_reference.artifact_id"
        )

    estimator_art = store.get_artifact(estimator_artifact_id)
    if estimator_art is None:
        raise ValueError(
            f"apply_model: estimator artifact {estimator_artifact_id!r} not found"
        )

    estimator_bytes = read_estimator_artifact(
        store, estimator_art,
        expected_logical_hash=estimator_ref.get("logical_hash"),
    )
    estimator = joblib.load(io.BytesIO(estimator_bytes))

    model_family = model.get("model_family", "unknown")
    has_scorecard = scorecard is not None

    data_arts = [a for a in context.input_artifacts if a.role in _DATA_ROLES]
    outputs: list[ArtifactRef] = []
    roles_evidence: dict[str, JsonDict] = {}

    for data_art in data_arts:
        df = pl.read_parquet(store.artifact_path(data_art))
        role = data_art.role
        missing = [f for f in features if f not in df.columns]
        if missing:
            raise ValueError(f"apply_model: role {role!r} missing features {missing}")

        X = df.select(features).to_numpy()

        if hasattr(estimator, "predict_proba"):
            proba = estimator.predict_proba(X)
            if proba.shape[1] > prob_col_idx:
                pred_bad = proba[:, prob_col_idx]
            else:
                pred_bad = proba[:, -1]
        else:
            raw_output = estimator.predict(X)
            pred_bad = raw_output.astype(np.float64)

        base_metadata: JsonDict = {
            "model_artifact_id": model_art.artifact_id,
            "model_family": model_family,
        }
        if scorecard_art is not None:
            base_metadata["scorecard_artifact_id"] = scorecard_art.artifact_id
        if bundle_art is not None:
            base_metadata["frozen_bundle_artifact_id"] = bundle_art.artifact_id

        output_cols = ["predicted_bad_probability", "model_artifact_id", "model_family"]
        add_exprs = [
            pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
            pl.lit(model_art.artifact_id).alias("model_artifact_id"),
            pl.lit(model_family).alias("model_family"),
        ]

        if has_scorecard:
            offset = float(scorecard.get("offset", 0))
            factor = float(scorecard.get("factor", 1))
            higher_is_lower = scorecard.get("higher_score_is_lower_risk", True)
            direction = -1.0 if higher_is_lower else 1.0
            log_odds = np.log(np.clip(pred_bad / np.maximum(1 - pred_bad, 1e-15), 1e-15, None))
            score_vals = offset + direction * factor * log_odds
            score_series = pl.Series("score", score_vals, dtype=pl.Float64)
            add_exprs.append(score_series)
            add_exprs.append(score_series.alias("cardre_scaled_score"))
            output_cols.extend(["score", "cardre_scaled_score"])

        df = df.with_columns(add_exprs)
        art = write_parquet_artifact(
            store, artifact_type="dataset", role=role,
            stem=f"scored-{role}-{context.step_spec.step_id}",
            frame=df, metadata=base_metadata,
        )
        outputs.append(art)

        pd_series = df["predicted_bad_probability"]
        role_entry: JsonDict = {
            "source_artifact_id": data_art.artifact_id,
            "output_artifact_id": art.artifact_id,
            "row_count": df.height,
            "required_features": features,
            "missing_features": missing,
            "output_columns": output_cols,
            "pd_min": round(float(pd_series.min()), 6),
            "pd_max": round(float(pd_series.max()), 6),
            "pd_mean": round(float(pd_series.mean()), 6),
        }
        if has_scorecard and "score" in df.columns:
            score_series = df["score"]
            role_entry["score_min"] = round(float(score_series.min()), 2)
            role_entry["score_max"] = round(float(score_series.max()), 2)
            role_entry["score_mean"] = round(float(score_series.mean()), 2)
        roles_evidence[role] = role_entry

    evidence = _build_evidence(roles_evidence, model_art, scorecard_art, bundle_art)
    evidence_art = _write_evidence_artifact(store, evidence, context.step_spec.step_id)

    return NodeOutput(
        artifacts=outputs + [evidence_art],
        metrics={"output_count": len(outputs)},
    )


# ---------------------------------------------------------------------------
# Ensemble adapter (voting / weighted)
# ---------------------------------------------------------------------------


def _apply_ensemble(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_art: ArtifactRef | None = None,
    bundle_art: ArtifactRef | None = None,
) -> NodeOutput:
    store = context.store
    model_payload = model.get("model_payload", {})
    base_models = model_payload.get("base_models", [])
    ensemble_type = model_payload.get("ensemble_type", "voting")
    weights_list = model_payload.get("weights", None)
    voting = model_payload.get("voting", "soft")
    threshold = model_payload.get("threshold", 0.5)

    features = model.get("features", [])
    prob_col_idx = model.get("probability_column_index", 1)

    base_artifacts = []
    for bm in base_models:
        aid = bm.get("artifact_id", "")
        if not aid:
            continue
        art = store.get_artifact(aid)
        if art is None:
            continue
        try:
            base_artifacts.append(json.loads(store.artifact_path(art).read_text()))
        except Exception:
            continue

    if not base_artifacts:
        raise ValueError("No base model artifacts could be loaded for ensemble apply")

    data_arts = [a for a in context.input_artifacts if a.role in _DATA_ROLES]
    outputs: list[ArtifactRef] = []
    roles_evidence: dict[str, JsonDict] = {}

    model_family = model.get("model_family", "unknown")

    for data_art in data_arts:
        df = pl.read_parquet(store.artifact_path(data_art))
        role = data_art.role

        all_probs = []
        for bm_art in base_artifacts:
            bm_features = bm_art.get("feature_contract", {}).get("features", []) or bm_art.get("features", [])
            missing = [f for f in bm_features if f not in df.columns]
            if missing:
                raise ValueError(f"apply_model: ensemble base model role {role!r} missing features {missing}")

            bm_family = bm_art.get("model_family", "")
            bm_prob_col = bm_art.get("probability_column_index", 1)

            if bm_family == "logistic_regression":
                coefs = bm_art.get("coefficients", {})
                intercept = float(bm_art.get("intercept", 0))
                log_odds_expr = pl.lit(intercept)
                for feat in bm_features:
                    log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(float(coefs.get(feat, 0)))
                probs = df.select((1.0 / (1.0 + (-log_odds_expr).exp())).alias("_probs"))["_probs"].to_numpy()
            else:
                estimator_ref = bm_art.get("estimator_reference", {})
                estimator_art_id = estimator_ref.get("artifact_id", "")
                if not estimator_art_id:
                    raise ValueError("Ensemble base model missing estimator_reference")
                est_art = store.get_artifact(estimator_art_id)
                if est_art is None:
                    raise ValueError(f"Base model estimator artifact {estimator_art_id!r} not found")
                est_bytes = read_estimator_artifact(
                    store, est_art,
                    expected_logical_hash=estimator_ref.get("logical_hash"),
                )
                estimator = joblib.load(io.BytesIO(est_bytes))
                X = df.select(bm_features).to_numpy()
                if hasattr(estimator, "predict_proba"):
                    proba = estimator.predict_proba(X)
                    probs = proba[:, bm_prob_col] if proba.shape[1] > bm_prob_col else proba[:, -1]
                else:
                    probs = estimator.predict(X).astype(np.float64)
            all_probs.append(probs)

        prob_matrix = np.column_stack(all_probs)
        if ensemble_type == "weighted" and weights_list:
            weights = np.array(weights_list, dtype=np.float64)
            pred_bad = prob_matrix @ weights
        elif voting == "soft":
            pred_bad = np.mean(prob_matrix, axis=1)
        else:
            predictions = (prob_matrix >= threshold).astype(int)
            pred_bad = (np.sum(predictions, axis=1) > (len(base_artifacts) / 2)).astype(float)

        base_metadata: JsonDict = {
            "model_artifact_id": model_art.artifact_id,
            "model_family": model_family,
        }
        if bundle_art is not None:
            base_metadata["frozen_bundle_artifact_id"] = bundle_art.artifact_id

        output_cols = ["predicted_bad_probability", "model_artifact_id", "model_family"]
        add_exprs = [
            pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
            pl.lit(model_art.artifact_id).alias("model_artifact_id"),
            pl.lit(model_family).alias("model_family"),
        ]

        df = df.with_columns(add_exprs)
        art = write_parquet_artifact(
            store, artifact_type="dataset", role=role,
            stem=f"scored-{role}-{context.step_spec.step_id}",
            frame=df, metadata=base_metadata,
        )
        outputs.append(art)

        pd_series = df["predicted_bad_probability"]
        roles_evidence[role] = {
            "source_artifact_id": data_art.artifact_id,
            "output_artifact_id": art.artifact_id,
            "row_count": df.height,
            "required_features": features,
            "missing_features": [],
            "output_columns": output_cols,
            "pd_min": round(float(pd_series.min()), 6),
            "pd_max": round(float(pd_series.max()), 6),
            "pd_mean": round(float(pd_series.mean()), 6),
        }

    evidence = _build_evidence(roles_evidence, model_art, scorecard_art, bundle_art)
    evidence_art = _write_evidence_artifact(store, evidence, context.step_spec.step_id)

    return NodeOutput(
        artifacts=outputs + [evidence_art],
        metrics={"output_count": len(outputs)},
    )


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, Any] = {}


def register_adapter(model_family: str) -> None:
    """Register an adapter function for a model family."""
    def wrapper(func: Any) -> Any:
        _ADAPTERS[model_family] = func
        return func
    return wrapper  # type: ignore


# Register built-in adapters
_ADAPTERS["logistic_regression"] = _apply_logistic_model
for fam in ("decision_tree", "random_forest", "gbdt",
            "xgboost", "lightgbm", "catboost"):
    _ADAPTERS[fam] = _apply_sklearn_estimator
for fam in ("voting_ensemble", "weighted_ensemble"):
    _ADAPTERS[fam] = _apply_ensemble


def apply_model(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_art: ArtifactRef | None = None,
    bundle_art: ArtifactRef | None = None,
) -> NodeOutput:
    """Apply a model using the registered adapter for its family."""
    model_family = model.get("model_family", "logistic_regression")
    adapter = _ADAPTERS.get(model_family)
    if adapter is None:
        raise ValueError(
            f"apply_model: unsupported model_family {model_family!r}. "
            f"Supported families: {sorted(_ADAPTERS)}"
        )
    return adapter(context, model, model_art, scorecard_art, bundle_art)
