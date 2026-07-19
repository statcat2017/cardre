"""Shared training utilities for ML model nodes (sklearn & boosting)."""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np
import polars as pl

from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.execution.context import ExecutionContext

INTERNAL_COLUMN_PREFIX = "_"


@dataclass(frozen=True)
class SupervisedTrainingData:
    """Validated train frame and target evidence for supervised nodes."""

    frame: pl.DataFrame
    target_column: str
    good_values: frozenset[str]
    bad_values: frozenset[str]
    y_binary: np.ndarray
    metadata: Any

    def feature_columns(self, params: Mapping[str, Any]) -> list[str]:
        """Return eligible numeric modelling columns for this train frame."""
        return resolve_supervised_feature_columns(
            self.frame,
            target_column=self.target_column,
            params=params,
        )


def resolve_supervised_feature_columns(
    frame: pl.DataFrame,
    *,
    target_column: str,
    params: Mapping[str, Any],
) -> list[str]:
    """Resolve numeric, non-target, non-internal supervised features.

    ``include_columns`` and ``exclude_columns`` are read from *params*.
    Internal columns (names beginning with ``_``) are always excluded
    and cannot be selected with ``include_columns``.
    """
    include_columns = list(params.get("include_columns", []))
    exclude_columns = set(params.get("exclude_columns", []))

    missing = [column for column in include_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"include_columns references missing columns: {missing}")

    internal_includes = [
        column
        for column in include_columns
        if column.startswith(INTERNAL_COLUMN_PREFIX)
    ]
    if internal_includes:
        raise ValueError(
            "include_columns must not select internal columns: "
            f"{internal_includes}"
        )

    candidates = include_columns or list(frame.columns)
    excluded = exclude_columns | {target_column}

    # Validate explicit includes for numeric compatibility before filtering
    if include_columns:
        non_numeric_includes = [
            column for column in include_columns
            if column not in excluded
            and not column.startswith(INTERNAL_COLUMN_PREFIX)
            and not frame.schema[column].is_numeric()
        ]
        if non_numeric_includes:
            raise ValueError(
                "Non-numeric columns not supported without encoding: "
                f"{non_numeric_includes}. Use include_columns to select only numeric "
                "features, or add an encoding node."
            )

    features = [
        column
        for column in candidates
        if column not in excluded
        and not column.startswith(INTERNAL_COLUMN_PREFIX)
        and frame.schema[column].is_numeric()
    ]

    if not features:
        raise ValueError("No numeric supervised features available after exclusions")

    return features


def prepare_supervised_training_data(
    context: ExecutionContext,
    *,
    operation: str,
) -> SupervisedTrainingData:
    """Load and validate the train Artifact and modelling metadata.

    Returns a :class:`SupervisedTrainingData` with the train frame,
    resolved target evidence, and binary target vector.  Fails closed
    when metadata, target column, or class population are missing.
    """
    from cardre.modeling.target import TargetSpec

    store = context.store
    reader = ArtifactEvidenceReader(store)
    train_artifact = context.require_train_artifact(operation)

    meta = context.target_metadata()
    target_spec = TargetSpec.from_metadata(meta)
    if target_spec is None:
        raise ValueError(
            "Target metadata is required. Provide modelling metadata "
            "via a definition artifact before this node."
        )

    df = reader.read_dataframe(train_artifact)

    if target_spec.target_column not in df.columns:
        raise ValueError(
            f"Target column '{target_spec.target_column}' not found "
            f"in training data (columns: {list(df.columns)})"
        )

    target_spec.validate_known(df)
    y_binary = target_spec.encode_binary_strict(df).to_numpy()
    n_bad = int(y_binary.sum())
    n_good = len(y_binary) - n_bad
    if n_bad == 0:
        raise ValueError(
            "No bad-class rows found "
            f"(bad_values={sorted(target_spec.bad_values)})"
        )
    if n_good == 0:
        raise ValueError(
            "No good-class rows found "
            f"(good_values={sorted(target_spec.good_values)})"
        )

    return SupervisedTrainingData(
        frame=df,
        target_column=target_spec.target_column,
        good_values=frozenset(target_spec.good_values),
        bad_values=frozenset(target_spec.bad_values),
        y_binary=y_binary,
        metadata=meta,
    )


def _prepare_training_data(
    context: ExecutionContext,
    params: Mapping[str, Any],
) -> tuple[pl.DataFrame, list[str], str, set[str], set[str], np.ndarray, Any]:
    """Bridge from the legacy tuple interface to the deep preparation module.

    Returns (df, features, target_column, good_values, bad_values, y_binary, meta).
    """
    prepared = prepare_supervised_training_data(
        context,
        operation="_prepare_training_data",
    )
    return (
        prepared.frame,
        prepared.feature_columns(params),
        prepared.target_column,
        set(prepared.good_values),
        set(prepared.bad_values),
        prepared.y_binary,
        prepared.metadata,
    )


def _write_estimator(store: Any, clf: Any, step_id: str, run_id: str, model_family: str) -> Any:
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
