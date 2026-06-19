"""AutoBinningFitNode — supervised optimal binning via optbinning adapter.

Produces Cardre SCHEMA_BIN_DEFINITION output compatible with existing
CalculateWoeIvNode, WoeTransformTrainNode, and ApplyWoeMappingNode.
"""
from __future__ import annotations

from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_BIN_DEFINITION,
)
from cardre.engine.binning.optbinning_adapter import fit_variables
from cardre.engine.binning.diagnostics import run_all as run_diagnostics
from cardre.node_parameters import (
    MethodOption, NodeParameterSchema, ParameterConstraint, ParameterDefinition,
)


class AutoBinningFitNode(NodeType):
    node_type = "cardre.auto_binning_fit"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition", "report"]
    is_internal = True

    VALID_ENGINES = {"optbinning"}
    VALID_PREBINNING = {"cart"}
    VALID_SOLVERS = {"cp", "mip"}
    VALID_DIVERGENCES = {"iv", "js", "hellinger"}
    VALID_MONOTONIC = {"auto", "none", "ascending", "descending"}
    _NUMERIC_TYPES = {
        pl.Float64, pl.Float32, pl.Int64, pl.Int32,
        pl.Int16, pl.Int8, pl.UInt64, pl.UInt32, pl.UInt16, pl.UInt8,
    }

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Auto Binning Fit",
            methods=[
                MethodOption(
                    id="optbinning",
                    label="OptBinning",
                    status="available",
                    description="Supervised optimal binning using optbinning engine.",
                    params=[
                        ParameterDefinition(
                            name="engine",
                            label="Engine",
                            kind="string",
                            default="optbinning",
                            help_text="Binning engine to use.",
                            constraint=ParameterConstraint(enum_values=["optbinning"]),
                        ),
                        ParameterDefinition(
                            name="prebinning_method",
                            label="Prebinning Method",
                            kind="string",
                            default="cart",
                            help_text="Method for initial prebinning.",
                            constraint=ParameterConstraint(enum_values=["cart"]),
                        ),
                        ParameterDefinition(
                            name="solver",
                            label="Solver",
                            kind="string",
                            default="cp",
                            help_text="Optimization solver.",
                            constraint=ParameterConstraint(enum_values=["cp", "mip"]),
                        ),
                        ParameterDefinition(
                            name="divergence",
                            label="Divergence",
                            kind="string",
                            default="iv",
                            help_text="Divergence measure for binning optimality.",
                            constraint=ParameterConstraint(enum_values=["iv", "js", "hellinger"]),
                        ),
                        ParameterDefinition(
                            name="monotonic_trend",
                            label="Monotonic Trend",
                            kind="string",
                            default="auto",
                            help_text="Monotonicity constraint for WOE trend.",
                            constraint=ParameterConstraint(
                                enum_values=["auto", "none", "ascending", "descending"],
                            ),
                        ),
                        ParameterDefinition(
                            name="max_n_prebins",
                            label="Max N Prebins",
                            kind="integer",
                            help_text="Maximum number of prebins (optional).",
                            constraint=ParameterConstraint(min_value=1),
                        ),
                        ParameterDefinition(
                            name="min_prebin_size",
                            label="Min Prebin Size",
                            kind="float",
                            help_text="Minimum fraction of rows per prebin (optional, 0-1 exclusive).",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                        ),
                        ParameterDefinition(
                            name="max_n_bins",
                            label="Max N Bins",
                            kind="integer",
                            help_text="Maximum number of final bins (optional).",
                            constraint=ParameterConstraint(min_value=1),
                        ),
                        ParameterDefinition(
                            name="min_bin_size",
                            label="Min Bin Size",
                            kind="float",
                            help_text="Minimum fraction of rows per final bin (optional, 0-1 exclusive).",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                        ),
                        ParameterDefinition(
                            name="min_bin_n_event",
                            label="Min Bin N Event",
                            kind="integer",
                            help_text="Minimum number of event observations per bin (optional).",
                            constraint=ParameterConstraint(min_value=1),
                        ),
                        ParameterDefinition(
                            name="min_bin_n_nonevent",
                            label="Min Bin N Nonevent",
                            kind="integer",
                            help_text="Minimum number of non-event observations per bin (optional).",
                            constraint=ParameterConstraint(min_value=1),
                        ),
                        ParameterDefinition(
                            name="cat_cutoff",
                            label="Cat Cutoff",
                            kind="float",
                            help_text="Category frequency cutoff for categorical variables (optional, 0-1 exclusive).",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                        ),
                        ParameterDefinition(
                            name="time_limit",
                            label="Time Limit",
                            kind="integer",
                            help_text="Time limit in seconds for the solver (optional).",
                            constraint=ParameterConstraint(min_value=1),
                        ),
                        ParameterDefinition(
                            name="special_codes",
                            label="Special Codes",
                            kind="object",
                            default={},
                            help_text="Map of variable names to lists of special code values.",
                        ),
                        ParameterDefinition(
                            name="exclude_columns",
                            label="Exclude Columns",
                            kind="list",
                            default=[],
                            help_text="Column names to exclude from binning.",
                        ),
                    ],
                ),
            ],
            default_method="optbinning",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        engine = params.get("engine", "optbinning")
        if engine not in self.VALID_ENGINES:
            return [f"engine must be one of {sorted(self.VALID_ENGINES)}, got {engine!r}"]
        if engine == "optbinning":
            try:
                import optbinning  # noqa: F401
            except ImportError:
                errors.append(
                    "optbinning package not installed. "
                    "Install with: pip install cardre[optimal-binning]"
                )
        else:
            return errors

        pbm = params.get("prebinning_method", "cart")
        if pbm not in self.VALID_PREBINNING:
            errors.append(f"prebinning_method must be one of {self.VALID_PREBINNING}")

        solver = params.get("solver", "cp")
        if solver not in self.VALID_SOLVERS:
            errors.append(f"solver must be one of {self.VALID_SOLVERS}")

        divergence = params.get("divergence", "iv")
        if divergence not in self.VALID_DIVERGENCES:
            errors.append(f"divergence must be one of {self.VALID_DIVERGENCES}")

        trend = params.get("monotonic_trend", "auto")
        if trend not in self.VALID_MONOTONIC:
            errors.append(f"monotonic_trend must be one of {self.VALID_MONOTONIC}")

        for key in ("max_n_prebins", "max_n_bins", "min_bin_n_event",
                     "min_bin_n_nonevent", "time_limit"):
            v = params.get(key)
            if v is not None:
                try:
                    if int(v) < 1:
                        errors.append(f"{key} must be >= 1")
                except (ValueError, TypeError):
                    errors.append(f"{key} must be an integer")

        for key in ("min_prebin_size", "min_bin_size", "cat_cutoff"):
            v = params.get(key)
            if v is not None:
                try:
                    fv = float(v)
                    if not (0 < fv < 1):
                        errors.append(f"{key} must be between 0 and 1")
                except (ValueError, TypeError):
                    errors.append(f"{key} must be a number")

        return errors

    @staticmethod
    def _resolve_train_input(context: ExecutionContext) -> ArtifactRef:
        train_artifacts = [a for a in context.input_artifacts if a.role == "train"]
        if len(train_artifacts) != 1:
            raise ValueError(
                f"OptBinning requires exactly one train artifact, found {len(train_artifacts)}."
            )
        return train_artifacts[0]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)

        # Resolve input artifacts — train only, no leakage
        train_artifact = self._resolve_train_input(context)
        meta_def = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

        df = pl.read_parquet(store.artifact_path(train_artifact))
        target_column = meta_def.target_column
        good_values = set(str(v) for v in meta_def.good_values)
        bad_values = set(str(v) for v in meta_def.bad_values)

        if not target_column or target_column not in df.columns:
            raise ValueError(f"target_column '{target_column}' not found in training data")
        if not good_values or not bad_values:
            raise ValueError("good_values and bad_values must be non-empty")

        # Determine feature columns
        exclude_columns = set(params.get("exclude_columns", []))
        exclude_columns.add(target_column)

        feature_cols = [c for c in df.columns if c not in exclude_columns]
        if not feature_cols:
            raise ValueError("No feature columns available after exclusions")

        # Determine variable types
        variable_types: dict[str, str] = {}
        for col in feature_cols:
            dtype = df.schema[col]
            if dtype in self._NUMERIC_TYPES:
                variable_types[col] = "numerical"
            else:
                variable_types[col] = "categorical"

        special_codes: dict[str, list[Any]] = params.get("special_codes", {})

        # Run adapter
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

        # Run diagnostics (fit-time checks before WOE)
        diagnostics = run_diagnostics(
            result.variables,
            min_bins=2,
            min_bin_count=30,
        )

        # Build bin definition (Cardre SCHEMA_BIN_DEFINITION)
        from cardre.engine.binning.diagnostics import BinningDiagnostic

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
            var_entry = {
                "variable": var_result.variable,
                "dtype": var_result.dtype,
                "kind": "numeric" if var_result.dtype == "numerical" else "categorical",
                "bins": var_result.bins,
                "status": var_result.status,
            }
            if var_result.metrics:
                var_entry["metrics"] = var_result.metrics
            # Failed variables go to rejected list, not active definition
            if is_failed:
                var_entry["active"] = False
                if var_result.failure_reason:
                    var_entry["failure_reason"] = var_result.failure_reason
                rejected_vars.append(var_entry)
                all_warnings.append({
                    "code": "VARIABLE_FAILED",
                    "severity": "error",
                    "variable": var_result.variable,
                    "message": f"Variable failed optbinning fit; excluded from active definition",
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

        # Reject active numeric variables with no usable boundary (single bin, no splits)
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

        bin_def = {
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
        }

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

        # Variable summary (Parquet — supports UI sidebar, branch comparison)
        var_summary_rows = []
        for var_result in result.variables:
            metrics = var_result.metrics or {}
            row = {
                "variable": var_result.variable,
                "dtype": var_result.dtype,
                "kind": "numeric" if var_result.dtype == "numerical" else "categorical",
                "status": var_result.status,
                "active": var_result.status != "FAILED",
                "iv": metrics.get("iv"),
                "n_bins": metrics.get("n_bins"),
                "row_count": metrics.get("row_count"),
                "missing_count": metrics.get("missing_count"),
                "missing_rate": metrics.get("missing_rate"),
                "min_bin_count": metrics.get("min_bin_count"),
                "max_bin_pct": metrics.get("max_bin_pct"),
                "monotonic_woe": metrics.get("monotonic_woe"),
                "warning_count": len(var_result.warnings or []),
                "failure_reason": var_result.failure_reason,
            }
            var_summary_rows.append(row)

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

        # Engine manifest (secondary evidence — mirrors bin definition source)
        manifest = dict(result.manifest)
        manifest.update({
            "cardre_node_type": "cardre.binning",
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
