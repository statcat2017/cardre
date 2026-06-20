from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind, SCHEMA_BIN_DEFINITION
from cardre.node_parameters import (
    MethodOption, NodeParameterSchema, ParameterConstraint, ParameterDefinition,
)


class FineClassingNode(NodeType):
    node_type = "cardre.fine_classing"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Fine Classing",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Fine classing (equal-frequency binning with optional missing handling).",
                    params=[
                        ParameterDefinition(
                            name="max_bins",
                            label="Max Bins",
                            kind="integer",
                            default=20,
                            help_text="Maximum number of bins per numeric variable.",
                            constraint=ParameterConstraint(min_value=2),
                        ),
                        ParameterDefinition(
                            name="min_bin_fraction",
                            label="Min Bin Fraction",
                            kind="float",
                            default=0.05,
                            help_text="Minimum fraction of rows a bin must contain (exclusive bounds).",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                        ),
                        ParameterDefinition(
                            name="missing_policy",
                            label="Missing Policy",
                            kind="string",
                            default="separate_bin",
                            help_text="How to treat missing values: separate bin or ignore.",
                            constraint=ParameterConstraint(enum_values=["separate_bin", "ignore"]),
                        ),
                        ParameterDefinition(
                            name="max_categorical_levels",
                            label="Max Categorical Levels",
                            kind="integer",
                            default=50,
                            help_text="Maximum number of category levels to keep per categorical variable.",
                            constraint=ParameterConstraint(min_value=1),
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
            default_method="default",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        max_bins = params.get("max_bins", 20)
        try:
            if int(max_bins) < 2:
                errors.append("max_bins must be >= 2")
        except (ValueError, TypeError):
            errors.append("max_bins must be an integer")
        min_bin_fraction = params.get("min_bin_fraction", 0.05)
        try:
            if not (0 < float(min_bin_fraction) < 1):
                errors.append("min_bin_fraction must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("min_bin_fraction must be a number")
        missing_policy = params.get("missing_policy", "separate_bin")
        if missing_policy not in ("separate_bin", "ignore"):
            errors.append("missing_policy must be one of: separate_bin, ignore")
        max_categorical_levels = params.get("max_categorical_levels", 50)
        try:
            if int(max_categorical_levels) < 1:
                errors.append("max_categorical_levels must be >= 1")
        except (ValueError, TypeError):
            errors.append("max_categorical_levels must be an integer")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:

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
        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        meta_def = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

        df = pl.read_parquet(store.artifact_path(train_artifact))
        target_column = meta_def.target_column
        good_values = set(str(v) for v in meta_def.good_values)
        bad_values = set(str(v) for v in meta_def.bad_values)

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

        variables = []
        warnings: list[dict] = []

        for col in feature_cols:
            col_dtype = df.schema[col]
            is_numeric = col_dtype in (
                pl.Float64, pl.Float32, pl.Int64, pl.Int32,
                pl.Int16, pl.Int8, pl.UInt64, pl.UInt32, pl.UInt16, pl.UInt8,
            )

            if is_numeric:
                bins = self._bin_numeric(df, col, target_column, good_values, bad_values,
                                         max_bins, min_bin_fraction, missing_policy, warnings)
                variables.append({
                    "variable": col,
                    "kind": "numeric",
                    "bins": bins,
                })
            else:
                bins = self._bin_categorical(df, col, target_column, good_values, bad_values,
                                             max_categorical_levels, missing_policy, warnings)
                variables.append({
                    "variable": col,
                    "kind": "categorical",
                    "bins": bins,
                })

        bin_def = LifecycleBinDefinition.from_payload({
            "variables": variables,
            "warnings": warnings,
        }).to_payload()
        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"fine-classing-{context.step_spec.step_id}",
            payload=bin_def,
            metadata={
                "source_artifact_id": train_artifact.artifact_id,
                "target_column": target_column,
                "schema_version": SCHEMA_BIN_DEFINITION,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"variable_count": len(variables)})

    def _bin_numeric(
        self, df: pl.DataFrame, col: str, target_column: str,
        good_values: set, bad_values: set,
        max_bins: int, min_bin_fraction: float,
        missing_policy: str, warnings: list[dict],
    ) -> list[dict]:
        non_null = df.filter(pl.col(col).is_not_null())
        missing = df.filter(pl.col(col).is_null())

        good_list = list(good_values)
        bad_list = list(bad_values)

        bins = []
        bin_counter = 0

        if missing.height > 0 and missing_policy == "separate_bin":
            bin_counter += 1
            mb = self._make_bin_counts(missing, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "Missing",
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": None, "is_missing_bin": True,
                "row_count": mb["row_count"], "good_count": mb["good_count"], "bad_count": mb["bad_count"],
            })

        if non_null.height == 0:
            return bins

        n = non_null.height
        n_bins = min(max_bins, n)
        pre_count = 1 if missing.height > 0 and missing_policy == "separate_bin" else 0
        max_non_missing = max_bins - pre_count

        if max_non_missing <= 0:
            return bins

        actual_n_bins = min(n_bins, max_non_missing)

        binned = non_null.with_columns([
            pl.col(col).qcut(actual_n_bins, allow_duplicates=True, include_breaks=True).alias("_qcut_bin"),
            pl.col(target_column).cast(pl.String).alias("_tgt_str"),
        ])

        bin_stats = binned.with_columns([
            binned["_qcut_bin"].struct.field("breakpoint").alias("_brk"),
        ]).group_by("_brk", maintain_order=True).agg([
            pl.len().alias("row_count"),
            pl.col("_tgt_str").is_in(bad_list).sum().alias("bad_count"),
            pl.col("_tgt_str").is_in(good_list).sum().alias("good_count"),
        ]).sort("_brk")

        _all_bk = bin_stats["_brk"].to_list()
        col_min = float(non_null[col].min())
        prev_upper = col_min

        for i, rec in enumerate(bin_stats.to_dicts()):
            bin_counter += 1
            brk = rec["_brk"]
            row_count = rec["row_count"]
            bad_count = rec["bad_count"]
            good_count = rec["good_count"]

            is_last = i == len(bin_stats) - 1
            hi = None if brk == float("inf") else float(brk)
            lo = prev_upper
            lower_inc = True
            if i > 0:
                lower_inc = False
                lo = float(_all_bk[i - 1]) if _all_bk[i - 1] != float("inf") else prev_upper

            label = f"[{lo:.4g}, {hi:.4g}]" if lo is not None and hi is not None else f"[{lo:.4g}, +inf)" if lo is not None else "All values"
            prev_upper = hi if hi is not None else lo

            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": label,
                "lower": lo,
                "upper": hi,
                "lower_inclusive": lower_inc,
                "upper_inclusive": not is_last,
                "categories": None,
                "is_missing_bin": False,
                "row_count": row_count,
                "good_count": good_count,
                "bad_count": bad_count,
            })

            if row_count / n < min_bin_fraction:
                warnings.append({
                    "variable": col, "bin_id": bins[-1]["bin_id"],
                    "message": f"Bin fraction {row_count / n:.4f} is below min_bin_fraction {min_bin_fraction}",
                })

        if bin_counter == 0 and non_null.height > 0:
            bin_counter += 1
            bc = self._make_bin_counts(non_null, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}", "label": "All values",
                "lower": None, "upper": None, "lower_inclusive": False, "upper_inclusive": False,
                "categories": None, "is_missing_bin": False,
                "row_count": bc["row_count"], "good_count": bc["good_count"], "bad_count": bc["bad_count"],
            })

        return bins

    def _bin_categorical(
        self, df: pl.DataFrame, col: str, target_column: str,
        good_values: set, bad_values: set,
        max_categorical_levels: int, missing_policy: str,
        warnings: list[dict],
    ) -> list[dict]:
        non_null = df.filter(pl.col(col).is_not_null())
        missing = df.filter(pl.col(col).is_null())

        good_list = list(good_values)
        bad_list = list(bad_values)

        bins = []
        bin_counter = 0

        if missing.height > 0 and missing_policy == "separate_bin":
            bin_counter += 1
            mb = self._make_bin_counts(missing, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}", "label": "Missing",
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": None, "is_missing_bin": True,
                "row_count": mb["row_count"], "good_count": mb["good_count"], "bad_count": mb["bad_count"],
            })

        if non_null.height == 0:
            return bins

        vc = non_null[col].value_counts().sort(col, descending=True)
        all_levels = vc[col].to_list()

        other_categories: list = []
        if len(all_levels) > max_categorical_levels:
            other_categories = all_levels[max_categorical_levels:]
            all_levels = all_levels[:max_categorical_levels]
            warnings.append({
                "variable": col,
                "message": f"High cardinality: {len(all_levels) + len(other_categories)} categories, "
                          f"using top {max_categorical_levels} plus 'Other'",
                "dropped_categories": len(other_categories),
            })

        grouped = non_null.with_columns(
            pl.col(target_column).cast(pl.String).alias("_tgt_str"),
        ).group_by(col).agg([
            pl.len().alias("row_count"),
            pl.col("_tgt_str").is_in(bad_list).sum().alias("bad_count"),
            pl.col("_tgt_str").is_in(good_list).sum().alias("good_count"),
        ])

        level_map = {str(r[0]): {"row_count": r[1], "bad_count": r[2], "good_count": r[3]} for r in grouped.iter_rows()}

        for level in all_levels:
            key = str(level)
            stats = level_map.get(key)
            if stats is None or stats["row_count"] == 0:
                continue
            bin_counter += 1
            bad_count = stats["bad_count"]
            good_count = stats["good_count"]
            row_count = stats["row_count"]
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}", "label": key,
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": [level], "is_missing_bin": False,
                "row_count": row_count,
                "good_count": good_count,
                "bad_count": bad_count,
            })

        if other_categories:
            other_df = non_null.filter(pl.col(col).is_in(other_categories))
            if other_df.height > 0:
                other_stats = other_df.with_columns(
                    pl.col(target_column).cast(pl.String).alias("_tgt_str"),
                ).select([
                    pl.len().alias("row_count"),
                    pl.col("_tgt_str").is_in(bad_list).sum().alias("bad_count"),
                    pl.col("_tgt_str").is_in(good_list).sum().alias("good_count"),
                ])
                bin_counter += 1
                rc = other_stats["row_count"][0]
                bc = other_stats["bad_count"][0]
                gc = other_stats["good_count"][0]
                bins.append({
                    "bin_id": f"{col}_bin_{bin_counter:03d}", "label": "Other",
                    "lower": None, "upper": None,
                    "lower_inclusive": False, "upper_inclusive": False,
                    "categories": other_categories, "is_missing_bin": False, "is_other_bin": True,
                    "row_count": rc,
                    "good_count": gc,
                    "bad_count": bc,
                })

        return bins

    def _make_bin_counts(
        self, bin_df: pl.DataFrame, col: str, target_column: str,
        good_values: set, bad_values: set,
    ) -> dict:
        row_count = bin_df.height
        if target_column and target_column in bin_df.columns and (good_values or bad_values):
            target_series = bin_df[target_column].cast(pl.String)
            good_count = int(target_series.is_in(list(good_values)).sum()) if good_values else 0
            bad_count = int(target_series.is_in(list(bad_values)).sum()) if bad_values else 0
        else:
            good_count = 0
            bad_count = 0
        return {"row_count": row_count, "good_count": good_count, "bad_count": bad_count}


class ManualBinningNode(NodeType):
    node_type = "cardre.manual_binning"
    version = "1"
    category = "refinement"
    input_roles: list[str] = ["definition"]
    output_roles: list[str] = ["definition"]

    VALID_ACTIONS = {
        "merge_bins", "group_categories",
        "reject_variable", "reorder_missing_bin", "reorder_special_bin",
    }

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Manual Binning",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Apply manual binning overrides (merge, group, reject, reorder).",
                    params=[
                        ParameterDefinition(
                            name="overrides",
                            label="Overrides",
                            kind="list",
                            default=[],
                            help_text=(
                                "List of override objects. Each object requires: "
                                "variable (str), action (one of merge_bins, group_categories, "
                                "reject_variable, reorder_missing_bin, reorder_special_bin), "
                                "reason (str), source_bin_ids (list[str]), "
                                "and optionally new_label (str)."
                            ),
                        ),
                    ],
                ),
            ],
            default_method="default",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for i, override in enumerate(list(params.get("overrides", []))):
            prefix = f"overrides[{i}]"
            if not isinstance(override, dict):
                errors.append(f"{prefix} must be a dict")
                continue
            variable = override.get("variable", "")
            action = override.get("action", "")
            reason = override.get("reason", "")
            if not reason:
                errors.append(f"{prefix}: override for '{variable}' requires a non-empty reason")
            if action not in self.VALID_ACTIONS:
                errors.append(f"{prefix}: unsupported action '{action}'")
            source_bin_ids = override.get("source_bin_ids", [])
            if not isinstance(source_bin_ids, list):
                errors.append(f"{prefix}: source_bin_ids must be a list")
            if action == "merge_bins" and len(source_bin_ids) < 2:
                errors.append(f"{prefix}: merge_bins requires at least 2 source bins")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params
        overrides = params.get("overrides", [])
        reader = ArtifactEvidenceReader(store)

        bin_def_obj = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        sel_def = reader.find_optional(context.input_artifacts, EvidenceKind.SELECTION_DEFINITION)

        bin_def = bin_def_obj.to_dict()

        selected_vars: set[str] = set()
        if sel_def is not None:
            selected_vars = sel_def.selected_names

        errors = validate_manual_binning_overrides(bin_def, overrides, selected_vars if sel_def else None)
        if errors:
            raise ValueError("; ".join(errors))

        refined = apply_manual_binning_overrides(bin_def, overrides, selected_vars if sel_def else None)

        refined["schema_version"] = SCHEMA_BIN_DEFINITION
        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"manual-binning-{context.step_spec.step_id}",
            payload=refined,
            metadata={"override_count": len(overrides), "schema_version": SCHEMA_BIN_DEFINITION},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"override_count": len(overrides)})


from cardre.engine.binning.definition import LifecycleBinDefinition, LifecycleVariable


def validate_manual_binning_overrides(
    bin_def: dict, overrides: list[dict], selected_vars: set[str] | None = None
) -> list[str]:
    return LifecycleBinDefinition.validate_overrides(bin_def, overrides, selected_vars)


def apply_manual_binning_overrides(
    bin_def: dict, overrides: list[dict], selected_vars: set[str] | None = None
) -> dict:
    return LifecycleBinDefinition.apply_overrides(bin_def, overrides, selected_vars)
