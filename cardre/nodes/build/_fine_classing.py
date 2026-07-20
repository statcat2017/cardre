from __future__ import annotations

from typing import Any

import polars as pl

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.artifacts import write_json_artifact
from cardre.engine.binning.definition import SCHEMA_BIN_DEFINITION
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.build._fine_classing_numeric import bin_numeric
from cardre.nodes.build._fine_classing_categorical import bin_categorical


def run_fine_classing(context: ExecutionContext) -> NodeOutput:
    store = context.store
    params = context.validated_params
    max_bins = int(params.get("max_bins", 20))
    min_bin_fraction = float(params.get("min_bin_fraction", 0.05))
    missing_policy = params.get("missing_policy", "separate_bin")
    max_categorical_levels = int(params.get("max_categorical_levels", 50))
    exclude_columns = list(params.get("exclude_columns", []))

    if max_bins < 2:
        raise ValueError("max_bins must be >= 2")
    if not (0 < min_bin_fraction < 1):
        raise ValueError("min_bin_fraction must be between 0 and 1")
    if missing_policy not in ("separate_bin", "ignore"):
        raise ValueError("missing_policy must be one of: separate_bin, ignore")
    if max_categorical_levels < 1:
        raise ValueError("max_categorical_levels must be >= 1")

    reader = ArtifactEvidenceReader(store)
    train_artifact = context.require_train_artifact("cardre.automatic_binning")
    meta_def = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

    df = reader.read_dataframe(train_artifact)
    target_column = meta_def.target_column
    good_values = {str(v) for v in meta_def.good_values}
    bad_values = {str(v) for v in meta_def.bad_values}

    if not target_column:
        raise ValueError("Fine classing requires non-empty target_column in modelling metadata")
    if target_column not in df.columns:
        raise ValueError(f"Target column '{target_column}' not found")
    if not good_values or not bad_values:
        raise ValueError("Fine classing requires non-empty good_values and bad_values in modelling metadata")
    target_series = df[target_column].cast(pl.String)
    actual_good = int(target_series.is_in(list(good_values)).sum())
    actual_bad = int(target_series.is_in(list(bad_values)).sum())
    if actual_good == 0:
        raise ValueError(
            f"Fine classing: good_values {sorted(good_values)} not found in "
            f"target column '{target_column}'"
        )
    if actual_bad == 0:
        raise ValueError(
            f"Fine classing: bad_values {sorted(bad_values)} not found in "
            f"target column '{target_column}'"
        )
    exclude_columns = list(set(exclude_columns + [target_column]))

    feature_cols = [c for c in df.columns if c not in exclude_columns]

    variables: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for col in feature_cols:
        col_dtype = df.schema[col]
        is_numeric = col_dtype in (
            pl.Float64, pl.Float32, pl.Int64, pl.Int32,
            pl.Int16, pl.Int8, pl.UInt64, pl.UInt32, pl.UInt16, pl.UInt8,
        )

        if is_numeric:
            bins = bin_numeric(df, col, target_column, good_values, bad_values,
                               max_bins, min_bin_fraction, missing_policy, warnings)
            variables.append({
                "variable": col,
                "kind": "numeric",
                "bins": bins,
            })
        else:
            bins = bin_categorical(df, col, target_column, good_values, bad_values,
                                   max_categorical_levels, warnings)
            variables.append({
                "variable": col,
                "kind": "categorical",
                "bins": bins,
            })

    definition = {
        "schema_version": SCHEMA_BIN_DEFINITION,
        "variables": variables,
        "warnings": warnings,
    }

    art = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem=f"fine-classing-{context.step_spec.step_id}",
        payload=definition,
        metadata={"schema_version": SCHEMA_BIN_DEFINITION},
    )
    return NodeOutput(artifacts=[art], metrics={"variable_count": len(variables)})
