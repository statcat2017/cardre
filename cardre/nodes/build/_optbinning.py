"""Private optbinning adapter — _run_optbinning and helpers.

Moved from auto_binning_fit.py (deleted) to keep bins.py under the
line-count limit.  Imported by AutomaticBinningNode.run.
"""
from __future__ import annotations

from typing import Any

import polars as pl

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.domain.artifacts import ArtifactRef
from cardre.engine.binning.definition import SCHEMA_BIN_DEFINITION, LifecycleBinDefinition
from cardre.engine.binning.diagnostics import run_all as run_diagnostics
from cardre.engine.binning.optbinning_adapter import fit_variables
from cardre.execution.context import ExecutionContext, NodeOutput

_NUMERIC_TYPES = {
    pl.Float64, pl.Float32, pl.Int64, pl.Int32,
    pl.Int16, pl.Int8, pl.UInt64, pl.UInt32, pl.UInt16, pl.UInt8,
}


def _resolve_train_input(context: ExecutionContext) -> ArtifactRef:
    train_artifacts = [a for a in context.input_artifacts if a.role == "train"]
    if len(train_artifacts) != 1:
        raise ValueError(
            f"OptBinning requires exactly one train artifact, found {len(train_artifacts)}."
        )
    return train_artifacts[0]


def _run_optbinning(context: ExecutionContext) -> NodeOutput:
    store = context.store
    params = context.validated_params
    reader = ArtifactEvidenceReader(store)

    train_artifact = _resolve_train_input(context)
    meta_def = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

    df = reader.read_dataframe(train_artifact)
    target_column = meta_def.target_column
    good_values = {str(v) for v in meta_def.good_values}
    bad_values = {str(v) for v in meta_def.bad_values}

    if not target_column or target_column not in df.columns:
        raise ValueError(f"target_column '{target_column}' not found in training data")
    if not good_values or not bad_values:
        raise ValueError("good_values and bad_values must be non-empty")

    exclude_columns = set(params.get("exclude_columns", []))
    exclude_columns.add(target_column)

    feature_cols = [c for c in df.columns if c not in exclude_columns]
    if not feature_cols:
        raise ValueError("No feature columns available after exclusions")

    variable_types: dict[str, str] = {}
    for col in feature_cols:
        dtype = df.schema[col]
        if dtype in _NUMERIC_TYPES:
            variable_types[col] = "numerical"
        else:
            variable_types[col] = "categorical"

    special_codes: dict[str, list[Any]] = params.get("special_codes", {})

    result = fit_variables(
        df=df,
        target=target_column,
        good_values=good_values,
        bad_values=bad_values,
        variable_names=feature_cols,
        variable_types=variable_types,
        special_codes=special_codes,
        params=params,
    )

    diagnostics = run_diagnostics(
        result.variables,
        min_bins=2,
        min_bin_count=30,
    )

    variables_out: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    for d in diagnostics:
        all_warnings.append({
            "code": d.code,
            "severity": d.severity,
            "variable": d.variable,
            "bin_id": d.bin_id,
            "message": d.message,
            "requires_acknowledgement": d.requires_acknowledgement,
            "details": d.details,
        })
    rejected_vars: list[dict[str, Any]] = []
    for var_result in result.variables:
        is_failed = var_result.status == "FAILED"
        var_entry: dict[str, Any] = {
            "variable": var_result.variable,
            "dtype": var_result.dtype,
            "kind": "numeric" if var_result.dtype == "numerical" else "categorical",
            "bins": var_result.bins,
            "status": var_result.status,
        }
        if var_result.metrics:
            var_entry["metrics"] = var_result.metrics
        if is_failed:
            var_entry["active"] = False
            if var_result.failure_reason:
                var_entry["failure_reason"] = var_result.failure_reason
            rejected_vars.append(var_entry)
            all_warnings.append({
                "code": "VARIABLE_FAILED",
                "severity": "error",
                "variable": var_result.variable,
                "message": "Variable failed optbinning fit; excluded from active definition",
                "requires_acknowledgement": True,
                "details": {},
            })
        else:
            var_entry["active"] = True
            variables_out.append(var_entry)
        for w in var_result.warnings:
            if isinstance(w, dict):
                all_warnings.append(w)
            else:
                all_warnings.append({
                    "code": "ADAPTER_WARNING",
                    "severity": "warning",
                    "variable": var_result.variable,
                    "message": str(w),
                    "details": {},
                })
        var_entry["warnings"] = [w for w in (var_result.warnings or []) if isinstance(w, dict)]

    for var_entry in variables_out:
        if var_entry.get("kind") == "numeric" and var_entry.get("status") == "OPTIMAL":
            bins = var_entry.get("bins", [])
            regular_bins = [b for b in bins if not b.get("is_missing_bin") and not b.get("is_special_bin")]
            if len(regular_bins) == 1:
                b = regular_bins[0]
                if b.get("lower") is None and b.get("upper") is None:
                    var_entry["active"] = False
                    var_entry["status"] = "REJECTED_NO_BOUNDARY"
                    var_entry["failure_reason"] = "Numeric variable has a single bin with no boundary; cannot be safely applied downstream."
                    rejected_vars.append(var_entry)
                    variables_out = [v for v in variables_out if v["variable"] != var_entry["variable"]]
                    all_warnings.append({
                        "code": "ALL_MISSING_OR_CONSTANT",
                        "severity": "error",
                        "variable": var_entry["variable"],
                        "message": "Numeric variable has a single bin with no boundary; rejected from active definitions.",
                        "requires_acknowledgement": True,
                        "details": {},
                    })

    bin_def = LifecycleBinDefinition.from_payload({
        "schema_version": SCHEMA_BIN_DEFINITION,
        "variables": variables_out,
        "rejected": rejected_vars if rejected_vars else [],
        "warnings": all_warnings + list(result.warnings),
        "source": {
            "engine": "optbinning",
            "engine_version": result.engine_version,
            "method": "optbinning",
            "node_id": context.step_spec.step_id,
            "fit_sample_role": "train",
            "train_artifact_id": train_artifact.artifact_id,
            "train_physical_hash": train_artifact.physical_hash,
            "train_logical_hash": train_artifact.logical_hash,
            "target_column": target_column,
            "good_values": sorted(good_values),
            "bad_values": sorted(bad_values),
            "params": context.validated_params,
        },
    }).to_payload()

    bin_artifact = write_json_artifact(
        store, artifact_type="definition", role="definition",
        stem=f"auto-binning-{context.step_spec.step_id}",
        payload=bin_def,
        metadata={
            "source_artifact_id": train_artifact.artifact_id,
            "target_column": target_column,
            "schema_version": SCHEMA_BIN_DEFINITION,
        },
    )

    summary_entries = variables_out + rejected_vars
    var_summary_rows = []
    for v in summary_entries:
        metrics = v.get("metrics") or {}
        var_summary_rows.append({
            "variable": v["variable"],
            "dtype": v.get("dtype"),
            "kind": v.get("kind"),
            "status": v.get("status"),
            "active": bool(v.get("active")),
            "iv": metrics.get("iv"),
            "n_bins": metrics.get("n_bins"),
            "row_count": metrics.get("row_count"),
            "missing_count": metrics.get("missing_count"),
            "missing_rate": metrics.get("missing_rate"),
            "min_bin_count": metrics.get("min_bin_count"),
            "max_bin_pct": metrics.get("max_bin_pct"),
            "monotonic_woe": metrics.get("monotonic_woe"),
            "warning_count": len(v.get("warnings") or []),
            "failure_reason": v.get("failure_reason"),
        })

    if var_summary_rows:
        var_summary_df = pl.DataFrame(var_summary_rows)
        var_summary_artifact = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem=f"auto-binning-summary-{context.step_spec.step_id}",
            frame=var_summary_df,
            metadata={
                "engine": "optbinning",
                "variable_count": len(var_summary_rows),
            },
            directory="artifacts",
        )
    else:
        empty_df = pl.DataFrame({"placeholder": []})
        var_summary_artifact = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem=f"auto-binning-summary-{context.step_spec.step_id}",
            frame=empty_df,
            metadata={"engine": "optbinning", "variable_count": 0},
            directory="artifacts",
        )

    manifest = dict(result.manifest)
    manifest.update({
        "cardre_node_type": "cardre.automatic_binning",
        "method": "optbinning",
        "fit_sample_role": "train",
        "train_artifact_id": train_artifact.artifact_id,
        "train_physical_hash": train_artifact.physical_hash,
        "train_logical_hash": train_artifact.logical_hash,
        "target_column": target_column,
        "good_values": sorted(good_values),
        "bad_values": sorted(bad_values),
    })
    manifest_artifact = write_json_artifact(
        store, artifact_type="report", role="report",
        stem=f"auto-binning-manifest-{context.step_spec.step_id}",
        payload=manifest,
        metadata={
            "engine": "optbinning",
            "engine_version": result.engine_version,
        },
    )

    metrics = {
        "variable_count": len(feature_cols),
        "succeeded": len(result.manifest.get("succeeded", [])),
        "failed": len(result.manifest.get("failed", [])),
        "warnings_count": len(all_warnings),
    }

    return NodeOutput(
        artifacts=[bin_artifact, var_summary_artifact, manifest_artifact],
        metrics=metrics,
    )
