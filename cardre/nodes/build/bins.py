from __future__ import annotations

from typing import Any

import polars as pl

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.artifacts import write_json_artifact
from cardre.engine.binning.definition import SCHEMA_BIN_DEFINITION, LifecycleBinDefinition
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.nodes.build._optbinning import _run_optbinning
from cardre.nodes.contracts import NodeType


class AutomaticBinningNode(NodeType):
    node_type = "cardre.automatic_binning"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition", "report"]

    VALID_METHODS = {"fine_classing", "optbinning"}

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Automatic Binning",
            default_method="fine_classing",
            methods=[
                MethodOption(
                    id="fine_classing",
                    label="Fine classing",
                    status="available",
                    description="Equal-frequency binning with optional missing handling.",
                    params=[
                        ParameterDefinition(
                            name="method",
                            label="Method",
                            kind="string",
                            default="fine_classing",
                        ),
                        ParameterDefinition(
                            name="max_bins",
                            label="Max bins",
                            kind="integer",
                            default=20,
                            constraint=ParameterConstraint(min_value=2),
                            help_text="Maximum number of bins per numeric variable.",
                        ),
                        ParameterDefinition(
                            name="min_bin_fraction",
                            label="Min bin fraction",
                            kind="float",
                            default=0.05,
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Minimum fraction of rows a bin must contain.",
                        ),
                        ParameterDefinition(
                            name="missing_policy",
                            label="Missing policy",
                            kind="string",
                            default="separate_bin",
                            constraint=ParameterConstraint(enum_values=["separate_bin", "ignore"]),
                            help_text="How to treat missing values.",
                        ),
                        ParameterDefinition(
                            name="max_categorical_levels",
                            label="Max categorical levels",
                            kind="integer",
                            default=50,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum levels per categorical variable.",
                        ),
                        ParameterDefinition(
                            name="exclude_columns",
                            label="Exclude columns",
                            kind="list",
                            default=[],
                            help_text="Column names to exclude from binning.",
                        ),
                    ],
                ),
                MethodOption(
                    id="optbinning",
                    label="OptBinning (supervised)",
                    status="available",
                    description="Supervised optimal binning using the optbinning engine.",
                    params=[
                        ParameterDefinition(
                            name="method",
                            label="Method",
                            kind="string",
                            default="optbinning",
                        ),
                        ParameterDefinition(
                            name="engine",
                            label="Engine",
                            kind="string",
                            default="optbinning",
                            constraint=ParameterConstraint(enum_values=["optbinning"]),
                            help_text="Binning engine to use.",
                        ),
                        ParameterDefinition(
                            name="prebinning_method",
                            label="Prebinning method",
                            kind="string",
                            default="cart",
                            constraint=ParameterConstraint(enum_values=["cart"]),
                            help_text="Method for initial prebinning.",
                        ),
                        ParameterDefinition(
                            name="solver",
                            label="Solver",
                            kind="string",
                            default="cp",
                            constraint=ParameterConstraint(enum_values=["cp", "mip"]),
                            help_text="Optimization solver.",
                        ),
                        ParameterDefinition(
                            name="divergence",
                            label="Divergence",
                            kind="string",
                            default="iv",
                            constraint=ParameterConstraint(enum_values=["iv", "js", "hellinger"]),
                            help_text="Divergence measure for binning optimality.",
                        ),
                        ParameterDefinition(
                            name="monotonic_trend",
                            label="Monotonic trend",
                            kind="string",
                            default="auto",
                            constraint=ParameterConstraint(
                                enum_values=["auto", "none", "ascending", "descending"],
                            ),
                            help_text="Monotonicity constraint for WOE trend.",
                        ),
                        ParameterDefinition(
                            name="max_n_prebins",
                            label="Max N prebins",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of prebins.",
                        ),
                        ParameterDefinition(
                            name="min_prebin_size",
                            label="Min prebin size",
                            kind="float",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Minimum fraction of rows per prebin.",
                        ),
                        ParameterDefinition(
                            name="max_n_bins",
                            label="Max N bins",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of final bins.",
                        ),
                        ParameterDefinition(
                            name="min_bin_size",
                            label="Min bin size",
                            kind="float",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Minimum fraction of rows per final bin.",
                        ),
                        ParameterDefinition(
                            name="min_bin_n_event",
                            label="Min bin N event",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Minimum event observations per bin.",
                        ),
                        ParameterDefinition(
                            name="min_bin_n_nonevent",
                            label="Min bin N nonevent",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Minimum non-event observations per bin.",
                        ),
                        ParameterDefinition(
                            name="cat_cutoff",
                            label="Category cutoff",
                            kind="float",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Category frequency cutoff for categorical variables.",
                        ),
                        ParameterDefinition(
                            name="time_limit",
                            label="Time limit",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Time limit in seconds for the solver.",
                        ),
                        ParameterDefinition(
                            name="special_codes",
                            label="Special codes",
                            kind="object",
                            default={},
                            help_text="Map of variable names to special code value lists.",
                        ),
                        ParameterDefinition(
                            name="exclude_columns",
                            label="Exclude columns",
                            kind="list",
                            default=[],
                            help_text="Column names to exclude from binning.",
                        ),
                    ],
                ),
                MethodOption(
                    id="chi_merge",
                    label="Chi-merge binning",
                    status="coming_soon",
                    description="Chi-square merge binning (coming soon).",
                    params=[],
                ),
                MethodOption(
                    id="tree_binning",
                    label="Decision tree binning",
                    status="coming_soon",
                    description="Supervised binning via decision tree splits (coming soon).",
                    params=[],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        method = params.get("method", "fine_classing")
        if method not in self.VALID_METHODS:
            errors.append(f"method must be one of {sorted(self.VALID_METHODS)}, got {method!r}")
            return errors

        if method == "fine_classing":
            errors.extend(self._validate_fine_classing(params))
        elif method == "optbinning":
            errors.extend(self._validate_optbinning(params))
        return errors

    def _validate_fine_classing(self, params: dict[str, Any]) -> list[str]:
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
        max_cat = params.get("max_categorical_levels", 50)
        try:
            if int(max_cat) < 1:
                errors.append("max_categorical_levels must be >= 1")
        except (ValueError, TypeError):
            errors.append("max_categorical_levels must be an integer")
        return errors

    def _validate_optbinning(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        engine = params.get("engine", "optbinning")
        if engine not in {"optbinning"}:
            return [f"engine must be one of {{'optbinning'}}, got {engine!r}"]
        if engine == "optbinning":
            try:
                import optbinning  # noqa: F401
            except ImportError:
                errors.append(
                    "optbinning package not installed. "
                    "Install with: pip install cardre[optimal-binning]"
                )

        pbm = params.get("prebinning_method", "cart")
        if pbm not in {"cart"}:
            errors.append("prebinning_method must be 'cart'")

        solver = params.get("solver", "cp")
        if solver not in {"cp", "mip"}:
            errors.append("solver must be one of {'cp', 'mip'}")

        divergence = params.get("divergence", "iv")
        if divergence not in {"iv", "js", "hellinger"}:
            errors.append("divergence must be one of {'iv', 'js', 'hellinger'}")

        trend = params.get("monotonic_trend", "auto")
        if trend not in {"auto", "none", "ascending", "descending"}:
            errors.append("monotonic_trend must be one of auto/none/ascending/descending")

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

    def run(self, context: ExecutionContext) -> NodeOutput:
        method = context.validated_params.get("method", "fine_classing")
        if method == "fine_classing":
            return _run_fine_classing(context)
        elif method == "optbinning":
            return _run_optbinning(context)
        raise ValueError(f"Unknown binning method: {method!r}")


def _run_fine_classing(context: ExecutionContext) -> NodeOutput:
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
            bins = _bin_numeric(df, col, target_column, good_values, bad_values,
                                max_bins, min_bin_fraction, missing_policy, warnings)
            variables.append({
                "variable": col,
                "kind": "numeric",
                "bins": bins,
            })
        else:
            bins = _bin_categorical(df, col, target_column, good_values, bad_values,
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
    df: pl.DataFrame, col: str, target_column: str,
    good_values: set[str], bad_values: set[str],
    max_bins: int, min_bin_fraction: float,
    missing_policy: str, warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    non_null = df.filter(pl.col(col).is_not_null())
    missing = df.filter(pl.col(col).is_null())

    good_list = list(good_values)
    bad_list = list(bad_values)

    bins: list[dict[str, Any]] = []
    bin_counter = 0

    if missing.height > 0 and missing_policy == "separate_bin":
        bin_counter += 1
        mb = _make_bin_counts(missing, col, target_column, good_values, bad_values)
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

    vc = non_null[col].value_counts().sort("count", descending=True)
    max_count = vc["count"][0]
    dup_ratio = max_count / n
    if dup_ratio > 0.5:
        dominant_val = vc[col][0]
        warnings.append({
            "code": "DUPLICATE_VALUES_CONCENTRATED",
            "variable": col,
            "concentration_ratio": round(float(dup_ratio), 4),
            "dominant_value": str(dominant_val),
            "message": f"Variable {col!r} has {int(max_count)}/{int(n)} rows "
                      f"({dup_ratio:.1%}) with the same value {dominant_val!r}; "
                      f"bin boundaries may be unstable.",
        })

    _all_bk = bin_stats["_brk"].to_list()
    col_min_raw: Any = non_null[col].min()
    col_min = float(col_min_raw) if col_min_raw is not None else 0.0
    prev_upper: float | None = col_min

    for i, rec in enumerate(bin_stats.to_dicts()):
        bin_counter += 1
        brk = rec["_brk"]
        row_count = rec["row_count"]
        bad_count = rec["bad_count"]
        good_count = rec["good_count"]

        is_last = i == len(bin_stats) - 1
        hi = None if brk == float("inf") else float(brk)
        if i == 0:
            lo = None
            lower_inc = False
        else:
            lower_inc = False
            lo = float(_all_bk[i - 1]) if _all_bk[i - 1] != float("inf") else prev_upper

        if lo is not None and hi is not None:
            label = f"({lo:.4g}, {hi:.4g}]"
        elif lo is not None:
            label = f"({lo:.4g}, +inf)"
        elif hi is not None:
            label = f"(-inf, {hi:.4g}]"
        else:
            label = "All values"
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
        bc = _make_bin_counts(non_null, col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}", "label": "All values",
            "lower": None, "upper": None, "lower_inclusive": False, "upper_inclusive": False,
            "categories": None, "is_missing_bin": False,
            "row_count": bc["row_count"], "good_count": bc["good_count"], "bad_count": bc["bad_count"],
        })

    return bins


def _bin_categorical(
    df: pl.DataFrame, col: str, target_column: str,
    good_values: set[str], bad_values: set[str],
    max_categorical_levels: int, missing_policy: str,
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    non_null = df.filter(pl.col(col).is_not_null())
    missing = df.filter(pl.col(col).is_null())

    good_list = list(good_values)
    bad_list = list(bad_values)

    bins: list[dict[str, Any]] = []
    bin_counter = 0

    if missing.height > 0 and missing_policy == "separate_bin":
        bin_counter += 1
        mb = _make_bin_counts(missing, col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}", "label": "Missing",
            "lower": None, "upper": None,
            "lower_inclusive": False, "upper_inclusive": False,
            "categories": None, "is_missing_bin": True,
            "row_count": mb["row_count"], "good_count": mb["good_count"], "bad_count": mb["bad_count"],
        })

    if non_null.height == 0:
        return bins

    vc = non_null[col].value_counts().sort("count", descending=True)
    all_levels = vc[col].to_list()

    other_categories: list[Any] = []
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

    level_map: dict[str, dict[str, int]] = {
        str(r[0]): {"row_count": int(r[1]), "bad_count": int(r[2]), "good_count": int(r[3])}
        for r in grouped.iter_rows()
    }

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
    bin_df: pl.DataFrame, col: str, target_column: str,
    good_values: set[str], bad_values: set[str],
) -> dict[str, int]:
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

    REASON_CODES = frozenset({
        "business_interpretability", "monotonicity", "sparse_bin",
        "zero_cell", "missing_value_treatment", "special_value_treatment",
        "regulatory_or_policy", "other",
    })

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
                                "and optionally new_label (str), reason_code (str) from: "
                                + ", ".join(sorted(ManualBinningNode.REASON_CODES)) + "."
                            ),
                        ),
                        ParameterDefinition(
                            name="reviewed",
                            label="Bin review complete",
                            kind="bool",
                            default=False,
                            help_text="Set to true when manual bin review is complete.",
                        ),
                        ParameterDefinition(
                            name="accept_automated",
                            label="Accept automated bins",
                            kind="bool",
                            default=False,
                            help_text="Set to true to accept automated bins without manual overrides (discards any overrides).",
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
            reason_code = override.get("reason_code")
            if not reason:
                errors.append(f"{prefix}: override for '{variable}' requires a non-empty reason")
            if reason_code is not None and reason_code not in self.REASON_CODES:
                errors.append(f"{prefix}: unknown reason_code '{reason_code}'")
            if action not in self.VALID_ACTIONS:
                errors.append(f"{prefix}: unsupported action '{action}'")
            source_bin_ids = override.get("source_bin_ids", [])
            if not isinstance(source_bin_ids, list):
                errors.append(f"{prefix}: source_bin_ids must be a list")
            if action == "merge_bins" and len(source_bin_ids) < 2:
                errors.append(f"{prefix}: merge_bins requires at least 2 source bins")
        if params.get("reviewed") and params.get("accept_automated"):
            errors.append("reviewed and accept_automated cannot both be true.")
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


def validate_manual_binning_overrides(
    bin_def: dict[str, Any], overrides: list[dict[str, Any]], selected_vars: set[str] | None = None
) -> list[str]:
    from cardre.engine.binning.definition import LifecycleBinDefinition
    typed = LifecycleBinDefinition.from_payload(bin_def)
    return LifecycleBinDefinition.validate_overrides(typed, overrides, selected_vars)


def apply_manual_binning_overrides(
    bin_def: dict[str, Any], overrides: list[dict[str, Any]], selected_vars: set[str] | None = None
) -> dict[str, Any]:
    from cardre.engine.binning.definition import LifecycleBinDefinition
    typed = LifecycleBinDefinition.from_payload(bin_def)
    result = LifecycleBinDefinition.apply_overrides(typed, overrides, selected_vars)
    return result.to_payload()
