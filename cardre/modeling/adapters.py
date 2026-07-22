from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any, cast

import joblib
import numpy as np
import polars as pl

from cardre.application.ports.artifact_store import (
    ArtifactReader,
    StagedArtifact,
    StagedArtifactWriter,
)
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_APPLY_MODEL_EVIDENCE
from cardre.modeling.families import get as get_family_spec
from cardre.modeling.families import list_families
from cardre.nodes.contracts import NodeResult

_DATA_ROLES = ("train", "test", "oot")


def _write_evidence_artifact(
    writer: StagedArtifactWriter,
    roles_evidence: dict[str, JsonDict],
    model_art: ArtifactRef,
    scorecard_artifact_id: str | None,
    bundle_artifact_id: str | None,
    step_id: str,
) -> StagedArtifact:
    evidence: JsonDict = {
        "schema_version": SCHEMA_APPLY_MODEL_EVIDENCE,
        "model_artifact_id": model_art.artifact_id,
        "roles": roles_evidence,
        "warnings": [],
    }
    if bundle_artifact_id is not None:
        evidence["frozen_bundle_artifact_id"] = bundle_artifact_id
    if scorecard_artifact_id is not None:
        evidence["scorecard_artifact_id"] = scorecard_artifact_id
    return writer.stage_json(
        role="report", kind=EvidenceKind.APPLY_MODEL_EVIDENCE.value,
        payload=evidence,
        metadata={"schema_version": SCHEMA_APPLY_MODEL_EVIDENCE},
    )


def _role_entry_from_df(
    df: pl.DataFrame,
    data_art: ArtifactRef,
    art: StagedArtifact,
    features: list[str],
    missing: list[str],
    output_cols: list[str],
    has_scorecard: bool,
) -> JsonDict:
    pd_series = df["predicted_bad_probability"]
    entry: JsonDict = {
        "source_artifact_id": data_art.artifact_id,
        "output_artifact_id": art.provisional_artifact_id,
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


def apply_logistic(
    artifact_reader: ArtifactReader,
    artifact_writer: StagedArtifactWriter,
    model: dict[str, Any],
    model_art: ArtifactRef,
    input_artifacts: list[ArtifactRef],
    step_id: str,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeResult:
    fc = model.get("feature_contract", {})
    features = fc.get("features", [])
    mp = model.get("model_payload", {})
    intercept = float(mp.get("intercept", 0))
    coefficients = mp.get("coefficients", {})
    has_scorecard = scorecard_parsed is not None

    if has_scorecard:
        offset = float(scorecard_parsed.get("offset", 0))
        factor_val = float(scorecard_parsed.get("factor", 1))
        direction = -1.0 if scorecard_parsed.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk" else 1.0
    else:
        offset, factor_val, direction = 0.0, 1.0, -1.0

    data_arts = [a for a in input_artifacts if a.role in _DATA_ROLES]
    staged: list[StagedArtifact] = []
    roles_evidence: dict[str, JsonDict] = {}

    for data_art in data_arts:
        data = artifact_reader.read_bytes(data_art)
        df = pl.read_parquet(io.BytesIO(data))
        role = data_art.role
        missing = [f for f in features if f not in df.columns]
        if missing:
            raise ValueError(f"apply_model: role {role!r} missing features {missing}")

        log_odds_expr = pl.lit(intercept)
        for feat in features:
            log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(float(coefficients.get(feat, 0)))

        prob_expr = (1.0 / (1.0 + (-log_odds_expr).exp())).alias("predicted_bad_probability")
        raw_expr = log_odds_expr.alias("raw_model_output")

        df = df.with_columns([prob_expr, raw_expr])

        if model.get("calibration"):
            raw_probs = df["predicted_bad_probability"].to_numpy()
            cal_probs = _apply_calibration(model, artifact_reader, raw_probs)
            df = df.with_columns([
                pl.Series("predicted_bad_probability", cal_probs, dtype=pl.Float64),
            ])
            cal_log_odds = np.log(
                np.clip(cal_probs / np.maximum(1 - cal_probs, 1e-15), 1e-15, None),
            )
            df = df.with_columns([
                pl.Series("raw_model_output", cal_log_odds, dtype=pl.Float64),
            ])

        base_metadata: JsonDict = {
            "model_artifact_id": model_art.artifact_id,
            "model_family": "logistic_regression",
            **({"scorecard_artifact_id": scorecard_artifact_id} if scorecard_artifact_id else {}),
            **({"frozen_bundle_artifact_id": bundle_artifact_id} if bundle_artifact_id else {}),
        }
        output_cols = [
            "predicted_bad_probability", "raw_model_output",
            "model_artifact_id", "model_family",
        ]
        add_exprs = [
            pl.lit(model_art.artifact_id).alias("model_artifact_id"),
            pl.lit("logistic_regression").alias("model_family"),
        ]
        if has_scorecard:
            score_expr = pl.lit(offset) + pl.lit(direction * factor_val) * pl.col("raw_model_output")
            add_exprs.append(score_expr.alias("score"))
            output_cols.append("score")

        df = df.with_columns(add_exprs)
        art = artifact_writer.stage_table(
            role=role, kind=EvidenceKind.SCORED_DATASET.value,
            frame=df, metadata=base_metadata,
        )
        staged.append(art)
        roles_evidence[role] = _role_entry_from_df(
            df, data_art, art, features, missing, output_cols, has_scorecard,
        )

    evidence_art = _write_evidence_artifact(
        artifact_writer, roles_evidence, model_art,
        scorecard_artifact_id, bundle_artifact_id, step_id,
    )
    staged.append(evidence_art)

    return NodeResult(
        staged_artifacts=staged,
        metrics={"output_count": len(data_arts)},
    )


def apply_sklearn_estimator(
    artifact_reader: ArtifactReader,
    artifact_writer: StagedArtifactWriter,
    model: dict[str, Any],
    model_art: ArtifactRef,
    input_artifacts: list[ArtifactRef],
    step_id: str,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeResult:
    estimator_ref = model.get("estimator_reference", {})
    estimator_artifact_id = estimator_ref.get("artifact_id", "")
    features = model.get("feature_contract", {}).get("features", [])
    prob_col_idx = model.get("probability_column_index", 1)

    if not estimator_artifact_id:
        raise ValueError("Non-logistic model requires estimator_reference.artifact_id")

    estimator_bytes = artifact_reader.read_bytes(estimator_artifact_id)
    estimator = joblib.load(io.BytesIO(estimator_bytes))

    model_family = model.get("model_family", "unknown")
    has_scorecard = scorecard_parsed is not None

    data_arts = [a for a in input_artifacts if a.role in _DATA_ROLES]
    staged: list[StagedArtifact] = []
    roles_evidence: dict[str, JsonDict] = {}

    for data_art in data_arts:
        data = artifact_reader.read_bytes(data_art)
        df = pl.read_parquet(io.BytesIO(data))
        role = data_art.role
        missing = [f for f in features if f not in df.columns]
        if missing:
            raise ValueError(f"apply_model: role {role!r} missing features {missing}")

        X = df.select(features).to_numpy()
        if hasattr(estimator, "predict_proba"):
            proba = estimator.predict_proba(X)
            if prob_col_idx < 0 or prob_col_idx >= proba.shape[1]:
                raise ValueError(
                    f"probability_column_index {prob_col_idx} is out of range "
                    f"for predict_proba output with {proba.shape[1]} columns",
                )
            pred_bad = proba[:, prob_col_idx]
        else:
            pred_bad = estimator.predict(X).astype(np.float64)

        if model.get("calibration"):
            pred_bad = _apply_calibration(model, artifact_reader, pred_bad)

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
            direction = -1.0 if scorecard_parsed.get("score_direction", "higher_is_lower_risk") == "higher_is_lower_risk" else 1.0
            log_odds = np.log(np.clip(pred_bad / np.maximum(1 - pred_bad, 1e-15), 1e-15, None))
            score_vals = offset + direction * factor * log_odds
            add_exprs.append(pl.Series("score", score_vals, dtype=pl.Float64))
            output_cols.append("score")

        df = df.with_columns(add_exprs)
        art = artifact_writer.stage_table(
            role=role, kind=EvidenceKind.SCORED_DATASET.value,
            frame=df, metadata=base_metadata,
        )
        staged.append(art)
        roles_evidence[role] = _role_entry_from_df(
            df, data_art, art, features, missing, output_cols, has_scorecard,
        )

    evidence_art = _write_evidence_artifact(
        artifact_writer, roles_evidence, model_art,
        scorecard_artifact_id, bundle_artifact_id, step_id,
    )
    staged.append(evidence_art)

    return NodeResult(
        staged_artifacts=staged,
        metrics={"output_count": len(data_arts)},
    )


def apply_ensemble(
    artifact_reader: ArtifactReader,
    artifact_writer: StagedArtifactWriter,
    model: dict[str, Any],
    model_art: ArtifactRef,
    input_artifacts: list[ArtifactRef],
    step_id: str,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeResult:
    model_payload = model.get("model_payload", {})
    ensemble_type = model_payload.get("ensemble_type", "voting")
    weights_list = model_payload.get("weights")
    voting = model_payload.get("voting", "soft")
    threshold = model_payload.get("threshold", 0.5)
    features = model.get("features", [])
    base_parsed = model.get("_base_models_parsed") or []
    if not base_parsed:
        raise ValueError("No base model data available for ensemble apply")

    model_family = model.get("model_family", "unknown")
    data_arts = [a for a in input_artifacts if a.role in _DATA_ROLES]
    staged: list[StagedArtifact] = []
    roles_evidence: dict[str, JsonDict] = {}

    for data_art in data_arts:
        data = artifact_reader.read_bytes(data_art)
        df = pl.read_parquet(io.BytesIO(data))
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
                bm_intercept = float(bm_art.get("intercept", 0))
                log_odds_expr = pl.lit(bm_intercept)
                for feat in bm_features:
                    log_odds_expr = log_odds_expr + pl.col(feat) * pl.lit(float(coefs.get(feat, 0)))
                probs = df.select((1.0 / (1.0 + (-log_odds_expr).exp())).alias("_probs"))["_probs"].to_numpy()
            else:
                estimator_ref = bm_art.get("estimator_reference", {})
                est_art_id = estimator_ref.get("artifact_id", "")
                if not est_art_id:
                    raise ValueError("Ensemble base model missing estimator_reference")
                est_bytes = artifact_reader.read_bytes(est_art_id)
                bm_estimator = joblib.load(io.BytesIO(est_bytes))
                X = df.select(bm_features).to_numpy()
                if hasattr(bm_estimator, "predict_proba"):
                    proba = bm_estimator.predict_proba(X)
                    if bm_prob_col < 0 or bm_prob_col >= proba.shape[1]:
                        raise ValueError(
                            f"ensemble base model probability_column_index {bm_prob_col} "
                            f"is out of range for predict_proba output with {proba.shape[1]} columns",
                        )
                    probs = proba[:, bm_prob_col]
                else:
                    probs = bm_estimator.predict(X).astype(np.float64)
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
        art = artifact_writer.stage_table(
            role=role, kind=EvidenceKind.SCORED_DATASET.value,
            frame=df, metadata=base_metadata,
        )
        staged.append(art)
        roles_evidence[role] = _role_entry_from_df(df, data_art, art, features, [], output_cols, False)

    evidence_art = _write_evidence_artifact(
        artifact_writer, roles_evidence, model_art, None, bundle_artifact_id, step_id,
    )
    staged.append(evidence_art)

    return NodeResult(
        staged_artifacts=staged,
        metrics={"output_count": len(data_arts)},
    )


def _apply_calibration(
    model: dict[str, Any],
    artifact_reader: ArtifactReader,
    y_prob: np.ndarray,
) -> np.ndarray:
    calibration = model.get("calibration")
    if not calibration:
        return y_prob

    application_mode = calibration.get("application_mode", "runtime_probability_transform")
    if application_mode == "folded_linear_log_odds":
        return y_prob

    calibrator_id = calibration.get("calibrator_artifact_id")
    if not calibrator_id:
        raise ValueError("Model has calibration block but no calibrator_artifact_id")

    calibrator_bytes = artifact_reader.read_bytes(calibrator_id)
    calibrator = joblib.load(io.BytesIO(calibrator_bytes))

    X_cal = np.column_stack([1.0 - y_prob, y_prob])

    if hasattr(calibrator, "predict_proba"):
        cal_probs = calibrator.predict_proba(X_cal)
        calibrated = cal_probs[:, 1] if cal_probs.shape[1] > 1 else cal_probs[:, 0]
    else:
        calibrated = calibrator.predict(y_prob)

    return cast(np.ndarray, np.asarray(calibrated, dtype=np.float64))


_ADAPTER_FNS: dict[str, Callable[..., NodeResult]] = {
    "apply_logistic": apply_logistic,
    "apply_sklearn_estimator": apply_sklearn_estimator,
}

_ADAPTERS: dict[str, Callable[..., NodeResult]] = {}

for _fam in list_families():
    spec = get_family_spec(_fam)
    if spec is not None and spec.adapter_fn in _ADAPTER_FNS:
        _ADAPTERS[_fam] = _ADAPTER_FNS[spec.adapter_fn]


def apply_model(
    artifact_reader: ArtifactReader,
    artifact_writer: StagedArtifactWriter,
    model: dict[str, Any],
    model_art: ArtifactRef,
    input_artifacts: list[ArtifactRef],
    step_id: str,
    scorecard_parsed: dict[str, Any] | None = None,
    scorecard_artifact_id: str | None = None,
    bundle_artifact_id: str | None = None,
) -> NodeResult:
    model_family = model.get("model_family", "logistic_regression")
    adapter = _ADAPTERS.get(model_family)
    if adapter is None:
        raise ValueError(
            f"apply_model: unsupported model_family {model_family!r}. "
            f"Supported families: {sorted(_ADAPTERS)}",
        )
    return adapter(
        artifact_reader, artifact_writer, model, model_art,
        input_artifacts, step_id,
        scorecard_parsed, scorecard_artifact_id, bundle_artifact_id,
    )
