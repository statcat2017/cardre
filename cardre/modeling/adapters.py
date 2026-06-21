"""Model family adapters for applying fitted models to score datasets.

All artifact file I/O (reading) must be done by the caller before calling
these adapters. Adapters receive already-parsed payloads and artifact
identifiers for metadata purposes only.
"""

from __future__ import annotations

import io
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
        scorecard_parsed: dict[str, Any] | None = None,
        scorecard_artifact_id: str | None = None,
        bundle_artifact_id: str | None = None,
    ) -> NodeOutput:
        ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DATA_ROLES = ("train", "test", "oot")


def _write_evidence_artifact(
    store: ProjectStore,
    roles_evidence: dict[str, JsonDict],
    model_art: ArtifactRef,
    scorecard_artifact_id: str | None,
    bundle_artifact_id: str | None,
    step_id: str,
) -> ArtifactRef:
    evidence: JsonDict = {
        "schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE,
        "model_artifact_id": model_art.artifact_id,
        "roles": roles_evidence,
        "warnings": [],
    }
    if bundle_artifact_id is not None:
        evidence["frozen_bundle_artifact_id"] = bundle_artifact_id
    if scorecard_artifact_id is not None:
        evidence["scorecard_artifact_id"] = scorecard_artifact_id
    return write_json_artifact(
        store, artifact_type="report", role="report",
        stem=f"score-apply-evidence-{step_id}",
        payload=evidence,
        metadata={"schema_version": SCHEMA_SCORE_APPLICATION_EVIDENCE},
    )


def _role_entry_from_df(
    df: pl.DataFrame,
    data_art: ArtifactRef,
    art: ArtifactRef,
    features: list[str],
    missing: list[str],
    output_cols: list[str],
    has_scorecard: bool,
) -> JsonDict:
    pd_series = df["predicted_bad_probability"]
    entry: JsonDict = {
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
        entry["score_min"] = round(float(score_series.min()), 2)
        entry["score_max"] = round(float(score_series.max()), 2)
        entry["score_mean"] = round(float(score_series.mean()), 2)
    return entry


# ---------------------------------------------------------------------------
# Logistic regression adapter
# ---------------------------------------------------------------------------


def apply_logistic(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeOutput:
    store = context.store
    features = model.get("features", [])
    intercept = float(model.get("intercept", 0))
    coefficients = model.get("coefficients", {})
    has_scorecard = scorecard_parsed is not None

    if has_scorecard:
        offset = float(scorecard_parsed.get("offset", 0))
        factor_val = float(scorecard_parsed.get("factor", 1))
        direction = -1.0 if scorecard_parsed.get("higher_score_is_lower_risk", True) else 1.0
    else:
        offset, factor_val, direction = 0.0, 1.0, -1.0

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
            log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(float(coefficients.get(feat, 0)))

        prob_expr = (1.0 / (1.0 + (-log_odds_expr).exp())).alias("predicted_bad_probability")
        raw_expr = log_odds_expr.alias("raw_model_output")

        base_metadata: JsonDict = {
            "model_artifact_id": model_art.artifact_id,
            "model_family": "logistic_regression",
            **({"scorecard_artifact_id": scorecard_artifact_id} if scorecard_artifact_id else {}),
            **({"frozen_bundle_artifact_id": bundle_artifact_id} if bundle_artifact_id else {}),
        }
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
        roles_evidence[role] = _role_entry_from_df(
            df, data_art, art, features, missing, output_cols, has_scorecard,
        )

    evidence_art = _write_evidence_artifact(
        store, roles_evidence, model_art,
        scorecard_artifact_id, bundle_artifact_id,
        context.step_spec.step_id,
    )
    return NodeOutput(artifacts=outputs + [evidence_art], metrics={"output_count": len(outputs)})


# ---------------------------------------------------------------------------
# Sklearn estimator adapter
# ---------------------------------------------------------------------------


def apply_sklearn_estimator(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeOutput:
    store = context.store

    estimator_ref = model.get("estimator_reference", {})
    estimator_artifact_id = estimator_ref.get("artifact_id", "")
    features = model.get("feature_contract", {}).get("features", []) or model.get("features", [])
    prob_col_idx = model.get("probability_column_index", 1)

    if not estimator_artifact_id:
        raise ValueError("Non-logistic model requires estimator_reference.artifact_id")

    estimator_art = store.get_artifact(estimator_artifact_id)
    if estimator_art is None:
        raise ValueError(f"Estimator artifact {estimator_artifact_id!r} not found")

    estimator_bytes = read_estimator_artifact(
        store, estimator_art,
        expected_logical_hash=estimator_ref.get("logical_hash"),
    )
    estimator = joblib.load(io.BytesIO(estimator_bytes))

    model_family = model.get("model_family", "unknown")
    has_scorecard = scorecard_parsed is not None

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
            pred_bad = proba[:, prob_col_idx] if proba.shape[1] > prob_col_idx else proba[:, -1]
        else:
            pred_bad = estimator.predict(X).astype(np.float64)

        base_metadata: JsonDict = {
            "model_artifact_id": model_art.artifact_id,
            "model_family": model_family,
            **({"scorecard_artifact_id": scorecard_artifact_id} if scorecard_artifact_id else {}),
            **({"frozen_bundle_artifact_id": bundle_artifact_id} if bundle_artifact_id else {}),
        }
        output_cols = ["predicted_bad_probability", "model_artifact_id", "model_family"]
        add_exprs = [
            pl.Series("predicted_bad_probability", pred_bad, dtype=pl.Float64),
            pl.lit(model_art.artifact_id).alias("model_artifact_id"),
            pl.lit(model_family).alias("model_family"),
        ]
        if has_scorecard:
            offset = float(scorecard_parsed.get("offset", 0))
            factor = float(scorecard_parsed.get("factor", 1))
            direction = -1.0 if scorecard_parsed.get("higher_score_is_lower_risk", True) else 1.0
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
        roles_evidence[role] = _role_entry_from_df(
            df, data_art, art, features, missing, output_cols, has_scorecard,
        )

    evidence_art = _write_evidence_artifact(
        store, roles_evidence, model_art,
        scorecard_artifact_id, bundle_artifact_id,
        context.step_spec.step_id,
    )
    return NodeOutput(artifacts=outputs + [evidence_art], metrics={"output_count": len(outputs)})


# ---------------------------------------------------------------------------
# Ensemble adapter (voting / weighted)
# ---------------------------------------------------------------------------


def apply_ensemble(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeOutput:
    """Apply ensemble model. scorecard_parsed is accepted for interface
    compatibility but ignored — ensemble scoring does not support
    scorecard scaling."""
    store = context.store
    model_payload = model.get("model_payload", {})
    base_models = model_payload.get("base_models", [])
    ensemble_type = model_payload.get("ensemble_type", "voting")
    weights_list = model_payload.get("weights", None)
    voting = model_payload.get("voting", "soft")
    threshold = model_payload.get("threshold", 0.5)
    features = model.get("features", [])
    prob_col_idx = model.get("probability_column_index", 1)
    base_parsed = model.get("_base_models_parsed", None) or []
    if not base_parsed:
        raise ValueError("No base model data available for ensemble apply")

    model_family = model.get("model_family", "unknown")
    data_arts = [a for a in context.input_artifacts if a.role in _DATA_ROLES]
    outputs: list[ArtifactRef] = []
    roles_evidence: dict[str, JsonDict] = {}

    for data_art in data_arts:
        df = pl.read_parquet(store.artifact_path(data_art))
        role = data_art.role

        all_probs = []
        for bm_art in base_parsed:
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
            pred_bad = prob_matrix @ np.array(weights_list, dtype=np.float64)
        elif voting == "soft":
            pred_bad = np.mean(prob_matrix, axis=1)
        else:
            pred_bad = (np.sum((prob_matrix >= threshold).astype(int), axis=1) > (len(base_parsed) / 2)).astype(float)

        base_metadata: JsonDict = {
            "model_artifact_id": model_art.artifact_id,
            "model_family": model_family,
            **({"scorecard_artifact_id": scorecard_artifact_id} if scorecard_artifact_id else {}),
            **({"frozen_bundle_artifact_id": bundle_artifact_id} if bundle_artifact_id else {}),
        }
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
        roles_evidence[role] = _role_entry_from_df(df, data_art, art, features, [], output_cols, False)

    evidence_art = _write_evidence_artifact(
        store, roles_evidence, model_art, None, bundle_artifact_id,
        context.step_spec.step_id,
    )
    return NodeOutput(artifacts=outputs + [evidence_art], metrics={"output_count": len(outputs)})


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, Any] = {}

for _fam in ("logistic_regression",):
    _ADAPTERS[_fam] = apply_logistic
for _fam in ("decision_tree", "random_forest", "gbdt",
             "xgboost", "lightgbm", "catboost"):
    _ADAPTERS[_fam] = apply_sklearn_estimator
for _fam in ("voting_ensemble", "weighted_ensemble"):
    _ADAPTERS[_fam] = apply_ensemble


def apply_model(
    context: ExecutionContext,
    model: dict[str, Any],
    model_art: ArtifactRef,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeOutput:
    """Apply a model using the registered adapter for its family.

    All artifact file I/O must be done before calling this function.
    Adapters receive already-parsed payloads.
    """
    model_family = model.get("model_family", "logistic_regression")
    adapter = _ADAPTERS.get(model_family)
    if adapter is None:
        raise ValueError(
            f"apply_model: unsupported model_family {model_family!r}. "
            f"Supported families: {sorted(_ADAPTERS)}"
        )
    return adapter(context, model, model_art, scorecard_parsed, scorecard_artifact_id, bundle_artifact_id)
