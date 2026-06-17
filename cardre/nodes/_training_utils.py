"""Shared training utilities for ML model nodes (sklearn & boosting)."""

from __future__ import annotations

import io
from typing import Any

import joblib
import numpy as np
import polars as pl

from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.audit import ExecutionContext


def _extract_target_metadata(
    store,
    input_artifacts,
) -> tuple[str, set[str], set[str], dict | None]:
    """Extract target column, good/bad values, and raw metadata from definition artifacts."""
    reader = ArtifactEvidenceReader(store)
    meta = reader.find_optional(input_artifacts, EvidenceKind.MODELLING_METADATA)
    if meta is None:
        return "", set(), set(), None
    return meta.target_column, set(str(v) for v in meta.good_values), set(str(v) for v in meta.bad_values), meta.extra


def _resolve_features(
    df: pl.DataFrame,
    target_column: str,
    params: dict[str, Any],
) -> list[str]:
    """Resolve feature columns from params and dataframe, excluding target."""
    include_columns = list(params.get("include_columns", []))
    exclude_columns = list(params.get("exclude_columns", []))

    if target_column:
        exclude_columns = list(set(exclude_columns + [target_column]))

    if include_columns:
        missing = [c for c in include_columns if c not in df.columns]
        if missing:
            raise ValueError(f"include_columns references missing columns: {missing}")
        features = [c for c in include_columns if c not in exclude_columns]
    else:
        features = [c for c in df.columns if c not in exclude_columns]

    if not features:
        raise ValueError("No feature columns available after exclusions")

    non_numeric = [
        c for c in features
        if not df.schema[c].is_numeric()
    ]
    if non_numeric:
        raise ValueError(
            f"Non-numeric columns not supported without encoding: {non_numeric}. "
            f"Use include_columns to select only numeric features, or add an encoding node."
        )

    return features


def _prepare_training_data(
    context: ExecutionContext,
    params: dict[str, Any],
) -> tuple[pl.DataFrame, list[str], str, set[str], set[str], np.ndarray, dict]:
    """Shared training data preparation for all sklearn model nodes.

    Returns (df, features, target_column, good_values, bad_values, y_binary, meta).
    """
    store = context.store
    train_artifact = next(a for a in context.input_artifacts if a.role == "train")

    target_column, good_values, bad_values, meta = _extract_target_metadata(
        store, context.input_artifacts,
    )

    if not target_column:
        raise ValueError("Target column is required")
    if not good_values:
        raise ValueError("Good values must be defined")
    if not bad_values:
        raise ValueError("Bad values must be defined")

    df = pl.read_parquet(store.artifact_path(train_artifact))

    if target_column not in df.columns:
        raise ValueError(f"Target column '{target_column}' not found in training data")

    features = _resolve_features(df, target_column, params)

    raw_target = df[target_column].cast(pl.String)
    target_is_bad = raw_target.is_in(bad_values)
    target_is_known = target_is_bad | raw_target.is_in(good_values)
    n_unknown = int((~target_is_known).sum())
    if n_unknown > 0:
        unknown_vals = sorted(raw_target.filter(~target_is_known).unique().to_list())
        raise ValueError(
            f"Target column '{target_column}' contains {n_unknown} value(s) "
            f"not declared as good or bad: {unknown_vals[:10]}. "
            f"Every row must be explicitly classified."
        )

    y_binary = target_is_bad.cast(pl.Int64).to_numpy()
    n_bad = int(y_binary.sum())
    n_good = len(y_binary) - n_bad
    if n_bad == 0:
        raise ValueError(f"No bad-class rows found (bad_values={sorted(bad_values)})")
    if n_good == 0:
        raise ValueError(f"No good-class rows found (good_values={sorted(good_values)})")

    return df, features, target_column, good_values, bad_values, y_binary, meta


def _write_estimator(store, clf, step_id: str, run_id: str, model_family: str):
    """Serialize a fitted sklearn estimator to a binary artifact."""
    buf = io.BytesIO()
    joblib.dump(clf, buf)
    estimator_bytes = buf.getvalue()
    from cardre.modeling.serialization import write_estimator_artifact
    return write_estimator_artifact(
        store,
        estimator_bytes=estimator_bytes,
        estimator_format="joblib",
        stem=f"{model_family}-estimator-{step_id}",
        creating_run_id=run_id,
        creating_run_step_id=step_id,
        metadata={"model_family": model_family},
    )
