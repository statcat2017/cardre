from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np
import polars as pl

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import InputCollection, OutputPublisher

INTERNAL_COLUMN_PREFIX = "_"


@dataclass(frozen=True)
class SupervisedTrainingData:
    frame: pl.DataFrame
    target_column: str
    good_values: frozenset[str]
    bad_values: frozenset[str]
    y_binary: np.ndarray
    metadata: Any

    def feature_columns(self, params: Mapping[str, Any]) -> list[str]:
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
            f"{internal_includes}",
        )

    candidates = include_columns or list(frame.columns)
    excluded = exclude_columns | {target_column}

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
                "features, or add an encoding node.",
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
    inputs: InputCollection,
    *,
    operation: str,
) -> SupervisedTrainingData:
    from cardre.modeling.target import TargetSpec

    train_artifact = inputs.require("train", operation)

    meta = inputs.target_metadata()
    target_spec = TargetSpec.from_metadata(meta)
    if target_spec is None:
        raise ValueError(
            "Target metadata is required. Provide modelling metadata "
            "via a definition artifact before this node.",
        )

    df = inputs.read_dataframe(train_artifact)

    if target_spec.target_column not in df.columns:
        raise ValueError(
            f"Target column '{target_spec.target_column}' not found "
            f"in training data (columns: {list(df.columns)})",
        )

    target_spec.validate_known(df)
    y_binary = target_spec.encode_binary_strict(df).to_numpy()
    n_bad = int(y_binary.sum())
    n_good = len(y_binary) - n_bad
    if n_bad == 0:
        raise ValueError(
            "No bad-class rows found "
            f"(bad_values={sorted(target_spec.bad_values)})",
        )
    if n_good == 0:
        raise ValueError(
            "No good-class rows found "
            f"(good_values={sorted(target_spec.good_values)})",
        )

    return SupervisedTrainingData(
        frame=df,
        target_column=target_spec.target_column,
        good_values=frozenset(target_spec.good_values),
        bad_values=frozenset(target_spec.bad_values),
        y_binary=y_binary,
        metadata=meta,
    )


def write_estimator_output(
    outputs: OutputPublisher,
    clf: Any,
    step_id: str,
    run_id: str,
    model_family: str,
) -> Any:
    """Stage a joblib estimator through the NodeContext output publisher."""
    import hashlib

    buf = io.BytesIO()
    joblib.dump(clf, buf)
    estimator_bytes = buf.getvalue()
    return outputs.publish_bytes(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT,
        data=estimator_bytes,
        media_type="application/octet-stream",
        logical_hash=hashlib.sha256(estimator_bytes).hexdigest(),
        metadata={
            "estimator_format": "joblib",
            "byte_count": len(estimator_bytes),
            "creating_run_id": run_id,
            "creating_run_step_id": step_id,
            "model_family": model_family,
        },
    )
