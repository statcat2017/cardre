from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl
from sklearn.linear_model import LogisticRegression

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    json_logical_hash,
)
from cardre.evidence import (
    AmbiguousEvidenceError,
    ArtifactEvidenceReader,
    EvidenceKind,
    EvidenceNotFoundError,
    SCHEMA_BIN_DEFINITION,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_WOE_TABLE,
)



class FineClassingNode(NodeType):
    node_type = "cardre.fine_classing"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition"]

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

        bin_def = {
            "variables": variables,
            "warnings": warnings,
        }

        bin_def["schema_version"] = SCHEMA_BIN_DEFINITION
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

        bins = []
        bin_counter = 0

        if missing.height > 0 and missing_policy == "separate_bin":
            bin_counter += 1
            missing_bin = self._make_bin_counts(missing, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "Missing",
                "lower": None,
                "upper": None,
                "lower_inclusive": False,
                "upper_inclusive": False,
                "categories": None,
                "is_missing_bin": True,
                "row_count": missing_bin["row_count"],
                "good_count": missing_bin["good_count"],
                "bad_count": missing_bin["bad_count"],
            })

        if non_null.height == 0:
            return bins

        values = non_null[col].to_list()
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        n_bins = min(max_bins, n)
        bin_size = max(1, n // n_bins)

        is_first_bin = True
        pre_bin_count = 1 if missing.height > 0 and missing_policy == "separate_bin" else 0
        max_non_missing = max_bins - pre_bin_count
        i = 0
        while i < n and len(bins) - pre_bin_count < max_non_missing:
            non_missing = len(bins) - pre_bin_count
            is_last = non_missing >= max_non_missing - 1
            chunk = sorted_vals[i:i + bin_size] if not is_last else sorted_vals[i:]
            lower = chunk[0]
            upper = chunk[-1] if not is_last else None
            if i > 0 and not is_last:
                lower = sorted_vals[i]
            lower_inc = bool(is_first_bin or is_last or lower == upper)
            if is_last:
                label = f"{'[' if lower_inc else '('}{lower:.4g}, +inf)"
                bin_df = non_null.filter(
                    pl.col(col) >= lower if lower_inc else pl.col(col) > lower
                )
            else:
                label = f"{'[' if lower_inc else '('}{lower:.4g}, {upper:.4g}]"
                bin_df = non_null.filter(
                    (pl.col(col) >= lower if lower_inc else pl.col(col) > lower) & (pl.col(col) <= upper)
                )

            bin_counter += 1
            bin_counts = self._make_bin_counts(bin_df, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": label,
                "lower": lower,
                "upper": upper,
                "lower_inclusive": lower_inc,
                "upper_inclusive": not is_last,
                "categories": None,
                "is_missing_bin": False,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
            })
            is_first_bin = False
            if is_last:
                i = n
            else:
                i += bin_size

        total_n = non_null.height
        for b in bins:
            if not b.get("is_missing_bin") and total_n > 0:
                frac = b["row_count"] / total_n
                if frac < min_bin_fraction:
                    warnings.append({
                        "variable": col,
                        "bin_id": b["bin_id"],
                        "message": f"Bin fraction {frac:.4f} is below min_bin_fraction {min_bin_fraction}",
                    })

        if bin_counter == 0 and non_null.height > 0:
            bin_counter += 1
            bin_counts = self._make_bin_counts(non_null, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "All values",
                "lower": None,
                "upper": None,
                "lower_inclusive": False,
                "upper_inclusive": False,
                "categories": None,
                "is_missing_bin": False,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
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

        value_counts = non_null[col].value_counts().sort(col, descending=True)
        all_levels = value_counts[col].to_list()

        other_categories: list = []
        if len(all_levels) > max_categorical_levels:
            top_levels = all_levels[:max_categorical_levels]
            other_categories = all_levels[max_categorical_levels:]
            warnings.append({
                "variable": col,
                "message": f"High cardinality: {len(all_levels)} categories, "
                          f"using top {max_categorical_levels} plus 'Other'",
                "dropped_categories": len(other_categories),
            })
            all_levels = top_levels

        bins = []
        bin_counter = 0

        if missing.height > 0 and missing_policy == "separate_bin":
            bin_counter += 1
            bin_counts = self._make_bin_counts(missing, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "Missing",
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": None,
                "is_missing_bin": True,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
            })

        for level in all_levels:
            bin_counter += 1
            bin_df = non_null.filter(pl.col(col) == level)
            count = bin_df.height
            if count == 0:
                continue
            bin_counts = self._make_bin_counts(bin_df, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": str(level),
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": [level],
                "is_missing_bin": False,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
            })

        if other_categories:
            bin_counter += 1
            other_df = non_null.filter(pl.col(col).is_in(other_categories))
            if other_df.height > 0:
                bin_counts = self._make_bin_counts(other_df, col, target_column, good_values, bad_values)
                bins.append({
                    "bin_id": f"{col}_bin_{bin_counter:03d}",
                    "label": "Other",
                    "lower": None, "upper": None,
                    "lower_inclusive": False, "upper_inclusive": False,
                    "categories": other_categories,
                    "is_missing_bin": False,
                    "is_other_bin": True,
                    "row_count": bin_counts["row_count"],
                    "good_count": bin_counts["good_count"],
                    "bad_count": bin_counts["bad_count"],
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


class CalculateWoeIvNode(NodeType):
    node_type = "cardre.calculate_woe_iv"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        zero_cell_policy = params.get("zero_cell_policy", "block")
        smoothing = params.get("smoothing")
        purpose = params.get("purpose", "initial")

        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        meta_def = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

        df = pl.read_parquet(store.artifact_path(train_artifact))

        target_column = meta_def.target_column
        good_values = set(str(v) for v in meta_def.good_values)
        bad_values = set(str(v) for v in meta_def.bad_values)

        if not target_column or target_column not in df.columns:
            raise ValueError(f"WOE/IV target column {target_column!r} not found in training data")
        if not good_values or not bad_values:
            raise ValueError("WOE/IV requires non-empty good_values and bad_values")
        target_series = df[target_column].cast(pl.String)
        total_good_all = int(target_series.is_in(list(good_values)).sum())
        total_bad_all = int(target_series.is_in(list(bad_values)).sum())
        if total_good_all == 0 or total_bad_all == 0:
            raise ValueError(
                f"WOE/IV requires at least one good and one bad row; found goods={total_good_all}, bads={total_bad_all}"
            )
        woe_rows: list[dict] = []
        iv_rows: dict[str, dict] = {}
        warnings_list: list[dict] = []

        # Track per-variable smoothing for controlled evidence artifact
        evidence_variables: list[dict] = []

        for var_def in bin_def.variables:
            variable = var_def.variable
            kind = var_def.kind
            bins = var_def.bins

            if variable not in df.columns:
                continue

            col_values = df[variable]

            total_good = total_good_all
            total_bad = total_bad_all

            var_woe_rows = []
            var_iv = 0.0
            zero_cell_count = 0
            smoothing_applied = False
            zero_cell_encountered = False
            affected_bins: list[dict] = []

            for bin_def in bins:
                bin_id = bin_def["bin_id"]
                label = bin_def["label"]
                is_missing = bin_def.get("is_missing_bin", False)

                if kind == "numeric":
                    lower = bin_def.get("lower")
                    upper = bin_def.get("upper")
                    lower_inc = bin_def.get("lower_inclusive", False)
                    upper_inc = bin_def.get("upper_inclusive", True)

                    if is_missing:
                        bin_mask = col_values.is_null()
                    else:
                        conditions = []
                        if lower is not None:
                            conditions.append(col_values >= lower if lower_inc else col_values > lower)
                        if upper is not None:
                            conditions.append(col_values <= upper if upper_inc else col_values < upper)
                        if not conditions:
                            raise ValueError(
                                f"WOE/IV numeric bin {variable!r}:{bin_id!r} has no lower or upper boundary"
                            )
                        bin_mask = conditions[0] if len(conditions) == 1 else conditions[0]
                        for c in conditions[1:]:
                            bin_mask = bin_mask & c
                else:
                    categories = bin_def.get("categories", [])
                    if is_missing:
                        bin_mask = col_values.is_null()
                    elif bin_def.get("is_other_bin", False):
                        explicit_categories = []
                        for other_bin in bins:
                            if other_bin.get("is_missing_bin", False) or other_bin.get("is_other_bin", False):
                                continue
                            explicit_categories.extend(other_bin.get("categories") or [])
                        bin_mask = col_values.is_not_null() & ~col_values.is_in(explicit_categories)
                    elif categories:
                        bin_mask = col_values.is_in(categories)
                    else:
                        bin_mask = pl.Series([False] * df.height)

                row_count = int(bin_mask.sum())

                if target_series is not None and good_values and bad_values:
                    bin_good = int(target_series.filter(bin_mask).is_in(list(good_values)).sum())
                    bin_bad = int(target_series.filter(bin_mask).is_in(list(bad_values)).sum())
                else:
                    bin_good = bin_def.get("good_count", 0)
                    bin_bad = bin_def.get("bad_count", 0)

                raw_good_dist = bin_good / total_good if total_good > 0 else 0.0
                raw_bad_dist = bin_bad / total_bad if total_bad > 0 else 0.0
                good_dist = raw_good_dist
                bad_dist = raw_bad_dist
                was_smoothed = False
                raw_woe_val: float | None = None

                if good_dist == 0.0 or bad_dist == 0.0:
                    zero_cell_count += 1
                    zero_cell_encountered = True
                    if zero_cell_policy == "block" and purpose == "final":
                        if smoothing and smoothing.get("method") == "additive":
                            alpha = float(smoothing.get("alpha", 0.5))
                            if alpha <= 0:
                                raise ValueError("Smoothing alpha must be positive")
                            if not smoothing.get("rationale"):
                                raise ValueError(
                                    f"Zero cell in variable {variable!r} bin {bin_id!r}: "
                                    f"smoothing configured without a rationale"
                                )
                            good_dist = (bin_good + alpha) / (total_good + alpha * len(bins)) if total_good > 0 else alpha / (alpha * len(bins))
                            bad_dist = (bin_bad + alpha) / (total_bad + alpha * len(bins)) if total_bad > 0 else alpha / (alpha * len(bins))
                            was_smoothed = True
                            smoothing_applied = True
                            warnings_list.append({
                                "variable": variable,
                                "bin_id": bin_id,
                                "message": f"Zero cell smoothed with additive alpha={alpha}",
                            })
                        else:
                            raise ValueError(
                                f"Zero cell in variable {variable!r} bin {bin_id!r}: "
                                f"good_dist={good_dist:.4f}, bad_dist={bad_dist:.4f}. "
                                f"Final WOE blocked by zero_cell_policy={zero_cell_policy!r}. "
                                f"Configure smoothing with a rationale to proceed."
                            )
                    elif smoothing and smoothing.get("method") == "additive":
                        alpha = float(smoothing.get("alpha", 0.5))
                        if alpha <= 0:
                            raise ValueError("Smoothing alpha must be positive")
                        good_dist = (bin_good + alpha) / (total_good + alpha * len(bins)) if total_good > 0 else alpha / (alpha * len(bins))
                        bad_dist = (bin_bad + alpha) / (total_bad + alpha * len(bins)) if total_bad > 0 else alpha / (alpha * len(bins))
                        was_smoothed = True
                        smoothing_applied = True

                if good_dist == 0.0 or bad_dist == 0.0:
                    woe_val = 0.0
                    iv_comp = 0.0
                else:
                    woe_val = float(math.log(good_dist / bad_dist))
                    iv_comp = (good_dist - bad_dist) * woe_val
                    if was_smoothed:
                        raw_woe_val = float(math.log(raw_good_dist / raw_bad_dist)) if raw_good_dist > 0 and raw_bad_dist > 0 else None

                var_iv += iv_comp

                var_woe_rows.append({
                    "variable": variable,
                    "bin_id": bin_id,
                    "label": label,
                    "row_count": row_count,
                    "good_count": bin_good,
                    "bad_count": bin_bad,
                    "good_distribution": round(good_dist, 6),
                    "bad_distribution": round(bad_dist, 6),
                    "woe": round(woe_val, 6),
                    "iv_component": round(iv_comp, 6),
                })

                if was_smoothed:
                    alpha = float(smoothing.get("alpha", 0.5))
                    affected_bins.append({
                        "bin_id": bin_id,
                        "reason": "zero_good" if raw_good_dist == 0.0 else "zero_bad",
                        "raw_good_count": bin_good,
                        "raw_bad_count": bin_bad,
                        "smoothed_good_count": bin_good + alpha,
                        "smoothed_bad_count": bin_bad + alpha,
                        "raw_woe": raw_woe_val,
                        "final_woe": round(woe_val, 6),
                    })

            woe_rows.extend(var_woe_rows)
            iv_rows[variable] = {
                "variable": variable,
                "iv": round(var_iv, 6),
                "bin_count": len(bins),
                "zero_cell_count": zero_cell_count,
                "warning_count": sum(1 for w in warnings_list if w["variable"] == variable),
            }

            var_bins_out = []
            for i, woe_row in enumerate(var_woe_rows):
                bd = bins[i] if i < len(bins) else {}
                var_bins_out.append({
                    "bin_id": woe_row["bin_id"],
                    "label": woe_row["label"],
                    "lower": bd.get("lower"),
                    "upper": bd.get("upper"),
                    "good_count": woe_row["good_count"],
                    "bad_count": woe_row["bad_count"],
                    "bad_rate": round(woe_row["bad_count"] / max(woe_row["good_count"] + woe_row["bad_count"], 1), 4),
                    "woe": woe_row["woe"],
                    "iv_contribution": woe_row["iv_component"],
                })

            evidence_variables.append({
                "variable_name": variable,
                "status": "included",
                "iv": round(var_iv, 6),
                "smoothing_applied": smoothing_applied,
                "zero_cell_encountered": zero_cell_encountered,
                "affected_bins": affected_bins,
                "bins": var_bins_out,
            })

        woe_table = pl.DataFrame(woe_rows) if woe_rows else pl.DataFrame({
            "variable": [], "bin_id": [], "label": [], "row_count": [],
            "good_count": [], "bad_count": [], "good_distribution": [],
            "bad_distribution": [], "woe": [], "iv_component": [],
        })
        iv_table = pl.DataFrame(list(iv_rows.values())) if iv_rows else pl.DataFrame({
            "variable": [], "iv": [], "bin_count": [],
            "zero_cell_count": [], "warning_count": [],
        })

        woe_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-table-{purpose}-{context.step_spec.step_id}",
            frame=woe_table,
            metadata={"purpose": purpose, "zero_cell_policy": zero_cell_policy, "schema_version": SCHEMA_WOE_TABLE},
        )
        iv_art = write_parquet_artifact(
            store, artifact_type="report", role="report",
            stem=f"iv-ranking-{purpose}-{context.step_spec.step_id}",
            frame=iv_table,
            metadata={"purpose": purpose, "zero_cell_policy": zero_cell_policy},
        )

        summary = {
            "purpose": purpose,
            "zero_cell_policy": zero_cell_policy,
            "smoothing": smoothing,
            "event_convention": "bad",
            "non_event_convention": "good",
            "woe_formula": "ln(non_event_distribution / event_distribution)",
            "variable_count": len(iv_rows),
            "warnings": warnings_list,
        }
        summary_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-summary-{purpose}-{context.step_spec.step_id}",
            payload=summary,
            metadata={"purpose": purpose},
        )

        # Controlled WOE/IV evidence artifact (Phase 5, cardre.woe_iv_evidence.v1)
        project_id = ""
        plan_id = store.get_plan_id_for_version(context.plan_version_id)
        if plan_id:
            plan = store.get_plan(plan_id)
            if plan:
                project_id = plan["project_id"]

        woe_evidence = {
            "schema_version": "cardre.woe_iv_evidence.v1",
            "project_id": project_id,
            "run_id": context.run_id,
            "branch_id": context.step_spec.branch_id or "",
            "step_id": context.step_spec.step_id,
            "canonical_step_id": context.step_spec.canonical_step_id,
            "dataset_role": "train",
            "target_column": target_column,
            "config": {
                "smoothing": {
                    "enabled": smoothing is not None,
                    "method": (smoothing or {}).get("method", "additive"),
                    "alpha": float((smoothing or {}).get("alpha", 0.5)),
                    "zero_cell_policy": zero_cell_policy,
                },
            },
            "variables": evidence_variables,
        }
        evidence_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-iv-evidence-{purpose}-{context.step_spec.step_id}",
            payload=woe_evidence,
            metadata={"purpose": purpose, "schema_version": "cardre.woe_iv_evidence.v1"},
        )

        all_artifacts = [woe_art, iv_art, summary_art, evidence_art]

        return NodeOutput(
            artifacts=all_artifacts,
            metrics={
                "variable_count": len(iv_rows),
                "zero_cell_warning_count": len(warnings_list),
            })


class VariableClusteringNode(NodeType):
    node_type = "cardre.variable_clustering"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "report"]
    output_roles: list[str] = ["report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        correlation_threshold = params.get("correlation_threshold", 0.7)
        try:
            if not (0 < float(correlation_threshold) < 1):
                errors.append("correlation_threshold must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("correlation_threshold must be a number")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params
        correlation_threshold = float(params.get("correlation_threshold", 0.7))
        candidate_limit = int(params.get("candidate_limit", 50))

        if not (0 < correlation_threshold < 1):
            raise ValueError("correlation_threshold must be between 0 and 1")

        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        iv_artifact = next((a for a in context.input_artifacts if a.role == "report"), None)

        df = pl.read_parquet(store.artifact_path(train_artifact))
        numeric_cols = [c for c in df.columns if df.schema[c].is_numeric()]
        numeric_cols = numeric_cols[:candidate_limit]

        clusters: list[dict] = []
        warnings: list[dict] = []

        if len(numeric_cols) < 2:
            for col in numeric_cols:
                clusters.append({
                    "cluster_id": f"singleton_{col}",
                    "variables": [col],
                    "reason": "Insufficient numeric columns for correlation clustering",
                })
            if numeric_cols:
                warnings.append({
                    "message": f"Only {len(numeric_cols)} numeric candidate(s); clustering is pass-through",
                })
        else:
            try:
                import numpy as np
                corr_matrix = df.select(numeric_cols).to_numpy()
                if corr_matrix.shape[1] == 0:
                    raise ValueError("Empty correlation matrix")
                corr = np.corrcoef(corr_matrix.T)

                assigned = set()
                cluster_id = 0
                for i, col_i in enumerate(numeric_cols):
                    if i in assigned:
                        continue
                    cluster_members = [col_i]
                    assigned.add(i)
                    for j, col_j in enumerate(numeric_cols):
                        if j in assigned or i == j:
                            continue
                        if abs(corr[i, j]) >= correlation_threshold:
                            cluster_members.append(col_j)
                            assigned.add(j)
                    cluster_id += 1
                    clusters.append({
                        "cluster_id": f"cluster_{cluster_id:03d}",
                        "variables": cluster_members,
                        "reason": f"Correlation >= {correlation_threshold}" if len(cluster_members) > 1
                                  else "Singleton (no correlated peers)",
                    })

                unassigned = [c for c in numeric_cols
                             if numeric_cols.index(c) not in assigned]
                for col in unassigned:
                    clusters.append({
                        "cluster_id": f"singleton_{col}",
                        "variables": [col],
                        "reason": "Singleton (not in any correlation cluster)",
                    })

            except (ImportError, ValueError):
                for col in numeric_cols:
                    clusters.append({
                        "cluster_id": f"singleton_{col}",
                        "variables": [col],
                        "reason": "Clustering unavailable (numpy not available); pass-through",
                    })
                warnings.append({"message": "Correlation clustering unavailable; using singleton pass-through"})

        clustering_report = {
            "correlation_threshold": correlation_threshold,
            "candidate_limit": candidate_limit,
            "total_candidates": len(numeric_cols),
            "clusters": clusters,
            "warnings": warnings,
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"clustering-{context.step_spec.step_id}",
            payload=clustering_report,
            metadata={"candidate_count": len(numeric_cols)},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"cluster_count": len(clusters)})


class VariableSelectionNode(NodeType):
    node_type = "cardre.variable_selection"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["report"]
    output_roles: list[str] = ["definition"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for key in ("manual_includes", "manual_excludes"):
            for entry in list(params.get(key, [])):
                if not isinstance(entry, dict):
                    errors.append(f"Each entry in {key} must be a dict with 'variable' and 'reason'")
                    continue
                if not entry.get("variable"):
                    errors.append(f"Entry in {key} missing 'variable'")
                if not entry.get("reason"):
                    errors.append(f"Entry in {key} for '{entry.get('variable', '')}' missing 'reason'")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params
        min_iv = float(params.get("min_iv", 0.02))
        max_variables = int(params.get("max_variables", 15))
        manual_entries_raw = list(params.get("manual_includes", []))
        manual_excludes_raw = list(params.get("manual_excludes", []))
        for entry in manual_entries_raw + manual_excludes_raw:
            if isinstance(entry, str):
                raise ValueError(
                    f"Manual include/exclude entry {entry!r} must be a dict "
                    f"with 'variable' and 'reason' keys"
                )
            if not entry.get("variable"):
                raise ValueError("Manual include/exclude entry missing 'variable'")
            if not entry.get("reason"):
                raise ValueError(
                    f"Manual include/exclude for variable {entry.get('variable')!r} "
                    f"requires a non-empty 'reason'"
                )
        manual_includes = [v["variable"] for v in manual_entries_raw]
        manual_excludes = [v["variable"] for v in manual_excludes_raw]
        manual_include_reasons = {v["variable"]: v["reason"] for v in manual_entries_raw}
        manual_exclude_reasons = {v["variable"]: v["reason"] for v in manual_excludes_raw}

        reader = ArtifactEvidenceReader(store)
        iv_lf = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        if iv_lf is not None:
            iv_df = iv_lf.collect()
            iv_cols = iv_df.columns
            iv_map = {}
            for row in iv_df.iter_rows():
                iv_map[str(row[iv_cols.index("variable")])] = {
                    "iv": float(row[iv_cols.index("iv")]),
                    "bin_count": int(row[iv_cols.index("bin_count")]),
                    "zero_cell_count": int(row[iv_cols.index("zero_cell_count")]),
                }
        else:
            iv_map = {}

        clusters: list[dict[str, Any]] = []
        for a in context.input_artifacts:
            if a.role == "report" and a.media_type == "application/json":
                try:
                    data = json.loads(store.artifact_path(a).read_text())
                    if "clusters" in data:
                        clusters = data["clusters"]
                        break
                except (json.JSONDecodeError, FileNotFoundError):
                    pass

        cluster_map: dict[str, str] = {}
        for cl in clusters:
            for var in cl.get("variables", []):
                cluster_map[var] = cl["cluster_id"]

        candidates = sorted(iv_map.keys(), key=lambda v: iv_map[v]["iv"], reverse=True)
        selected: list[dict] = []
        rejected: list[dict] = []
        seen_clusters: set[str] = set()

        for var in candidates:
            if var in manual_excludes:
                reason = manual_exclude_reasons.get(var, "Manual exclusion")
                rejected.append({"variable": var, "reason": reason})
                continue

        for var in candidates:
            if var in manual_excludes:
                continue
            if var in manual_includes:
                reason = manual_include_reasons.get(var, "Manual inclusion")
                selected.append({"variable": var, "reason": reason})
                seen_clusters.add(cluster_map.get(var, var))
                continue

            iv_info = iv_map[var]
            if iv_info["iv"] < min_iv:
                rejected.append({
                    "variable": var,
                    "reason": f"IV {iv_info['iv']:.4f} below threshold {min_iv}",
                })
                continue

            cluster_id = cluster_map.get(var, var)
            if cluster_id in seen_clusters:
                rejected.append({
                    "variable": var,
                    "reason": f"Lower IV than selected correlated variable in cluster {cluster_id}",
                })
                continue

            if len(selected) >= max_variables:
                rejected.append({
                    "variable": var,
                    "reason": f"Reached max_variables limit ({max_variables})",
                })
                continue

            selected.append({
                "variable": var,
                "reason": f"IV above threshold and strongest in cluster"
                         if cluster_id not in seen_clusters else
                         f"IV above threshold",
            })
            seen_clusters.add(cluster_id)

        selection = {
            "min_iv": min_iv,
            "max_variables": max_variables,
            "selected": selected,
            "rejected": rejected,
        }

        selection["schema_version"] = SCHEMA_SELECTION_DEFINITION
        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"variable-selection-{context.step_spec.step_id}",
            payload=selection,
            metadata={"selected_count": len(selected), "rejected_count": len(rejected), "schema_version": SCHEMA_SELECTION_DEFINITION},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"selected_count": len(selected), "rejected_count": len(rejected)})


class ManualBinningNode(NodeType):
    node_type = "cardre.manual_binning"
    version = "1"
    category = "refinement"
    input_roles: list[str] = ["definition"]
    output_roles: list[str] = ["definition"]

    VALID_ACTIONS = {"merge_bins", "group_categories", "isolate_missing", "isolate_special_value"}

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

        bin_artifacts = []
        selection_artifacts = []
        for a in context.input_artifacts:
            if a.role != "definition":
                continue
            try:
                payload = json.loads(store.artifact_path(a).read_text())
                if "variables" in payload and "selected" not in payload:
                    bin_artifacts.append(a)
                elif "selected" in payload:
                    selection_artifacts.append(a)
            except Exception:
                continue

        if len(bin_artifacts) != 1:
            raise ValueError(f"Manual binning requires exactly one bin definition artifact; found {len(bin_artifacts)}")
        if len(selection_artifacts) > 1:
            raise ValueError(f"Manual binning requires at most one selection artifact; found {len(selection_artifacts)}")
        bin_artifact = bin_artifacts[0]
        selection_artifact = selection_artifacts[0] if selection_artifacts else None

        bin_def = json.loads(store.artifact_path(bin_artifact).read_text())
        selected_vars: set[str] = set()
        if selection_artifact:
            sel = json.loads(store.artifact_path(selection_artifact).read_text())
            selected_vars = {s["variable"] for s in sel.get("selected", [])}

        errors = validate_manual_binning_overrides(bin_def, overrides, selected_vars if selection_artifact else None)
        if errors:
            raise ValueError("; ".join(errors))

        refined = apply_manual_binning_overrides(bin_def, overrides, selected_vars if selection_artifact else None)

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


class TechnicalManifestExportNode(NodeType):
    node_type = "cardre.technical_manifest_export"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["definition", "report"]
    output_roles: list[str] = ["manifest"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        run_id = context.run_id
        plan_version_id = context.plan_version_id

        run = store.get_run(run_id)
        plan_version = store.get_plan_version(plan_version_id)
        plan = None
        project = None
        if plan_version:
            plan_id = store.get_plan_id_for_version(plan_version_id)
            if plan_id:
                plan = store.get_plan(plan_id)
                if plan:
                    project = store.get_project(plan["project_id"])

        all_run_steps = store.get_run_steps(run_id)

        steps_evidence = []
        artifacts_evidence = []
        all_warnings: list[dict] = []
        all_errors: list[dict] = []

        seen_artifact_ids: set[str] = set()
        for rs in all_run_steps:
            step_info = {
                "step_id": rs.step_id,
                "node_type": rs.execution_fingerprint.get("node_type", ""),
                "node_version": rs.execution_fingerprint.get("node_version", ""),
                "status": rs.status,
                "params_hash": rs.execution_fingerprint.get("params_hash", ""),
                "input_artifact_logical_hashes": rs.execution_fingerprint.get("input_artifact_logical_hashes", []),
                "output_artifact_logical_hashes": rs.execution_fingerprint.get("output_artifact_logical_hashes", []),
            }
            steps_evidence.append(step_info)

            for aid in rs.output_artifact_ids:
                if aid in seen_artifact_ids:
                    continue
                seen_artifact_ids.add(aid)
                art = store.get_artifact(aid)
                if art:
                    artifacts_evidence.append({
                        "artifact_id": art.artifact_id,
                        "artifact_type": art.artifact_type,
                        "role": art.role,
                        "physical_hash": art.physical_hash,
                        "logical_hash": art.logical_hash,
                        "media_type": art.media_type,
                    })
            for w in rs.warnings:
                all_warnings.append(dict(w))
            for e in rs.errors:
                all_errors.append(dict(e))

        modelling_metadata = {}
        selected_variables = []
        model_artifact_data: dict = {}
        scorecard_artifact_data: dict = {}
        validation_metrics_data: dict = {}
        cutoff_data: dict = {}

        for rs in all_run_steps:
            node_type = rs.execution_fingerprint.get("node_type", "")
            for aid in rs.output_artifact_ids:
                art = store.get_artifact(aid)
                if art is None:
                    continue
                try:
                    if node_type == "cardre.define_modelling_metadata":
                        modelling_metadata = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.variable_selection":
                        sel = json.loads(store.artifact_path(art).read_text())
                        selected_variables = sel.get("selected", [])
                    elif node_type == "cardre.logistic_regression" and art.artifact_type == "model":
                        model_artifact_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.decision_tree_classifier" and art.artifact_type == "model":
                        model_artifact_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.score_scaling" and art.artifact_type == "scorecard":
                        scorecard_artifact_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.validation_metrics" and art.artifact_type == "report":
                        validation_metrics_data = json.loads(store.artifact_path(art).read_text())
                    elif node_type == "cardre.cutoff_analysis" and art.artifact_type == "report":
                        cutoff_data = json.loads(store.artifact_path(art).read_text())
                except (FileNotFoundError, json.JSONDecodeError):
                    pass

        manifest = {
            "project": {
                "project_id": project["project_id"] if project else "",
                "name": project["name"] if project else "",
            } if project else {},
            "run": {
                "run_id": run_id,
                "plan_version_id": plan_version_id,
            },
            "steps": steps_evidence,
            "artifacts": artifacts_evidence,
            "modelling_metadata": modelling_metadata,
            "selected_variables": selected_variables,
            "model": model_artifact_data,
            "scorecard": scorecard_artifact_data,
            "validation_metrics": validation_metrics_data,
            "cutoff_analysis": cutoff_data,
            "warnings": all_warnings,
            "errors": all_errors,
        }

        artifact = write_json_artifact(
            store, artifact_type="manifest", role="manifest",
            stem=f"technical-manifest-{context.step_spec.step_id}",
            payload=manifest,
            metadata={"run_id": run_id, "plan_version_id": plan_version_id},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"step_count": len(steps_evidence), "artifact_count": len(artifacts_evidence)})


class WoeTransformTrainNode(NodeType):
    node_type = "cardre.woe_transform_train"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition", "report"]
    output_roles: list[str] = ["train"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        reader = ArtifactEvidenceReader(store)
        train_artifact = next(a for a in context.input_artifacts if a.role == "train")

        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)

        try:
            meta = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        except (EvidenceNotFoundError, AmbiguousEvidenceError):
            meta = None
        sel = reader.find_optional(context.input_artifacts, EvidenceKind.SELECTION_DEFINITION)

        if not bin_def.variables:
            raise ValueError("WOE transform received an empty bin definition")
        target_column = meta.target_column if meta is not None else ""

        df = pl.read_parquet(store.artifact_path(train_artifact))
        bin_def_dict = bin_def.to_dict()
        woe_map = woe_table.mapping

        missing_woe_bins: list[str] = []
        for var_def in bin_def.variables:
            for bin_entry in var_def.bins:
                bin_id = bin_entry["bin_id"]
                if woe_map.get(var_def.variable, {}).get(bin_id) is None:
                    missing_woe_bins.append(f"{var_def.variable}:{bin_id}")

        if missing_woe_bins:
            raise ValueError(
                f"WOE transform: {len(missing_woe_bins)} bin(s) have no WOE mapping: "
                f"{', '.join(missing_woe_bins[:10])}"
            )

        selected_names: set[str] | None = None
        if sel is not None:
            selected_names = sel.selected_names

        all_var_defs = bin_def.variables
        if selected_names is not None:
            selected_vars = [v for v in all_var_defs if v.variable in selected_names]
            if not selected_vars:
                raise ValueError(
                    f"WOE transform: variable-selection defined {len(selected_names)} selected "
                    f"variable(s) but none found in bin definitions"
                )
        else:
            selected_vars = list(all_var_defs)

        woe_columns = []
        result_df = df

        for var_def in selected_vars:
            variable = var_def.variable if hasattr(var_def, 'variable') else var_def.get('variable', '')
            kind = var_def.kind if hasattr(var_def, 'kind') else var_def.get('kind', '')
            bins = var_def.bins if hasattr(var_def, 'bins') else var_def.get('bins', [])
            woe_col = f"{variable}_woe"

            if variable not in df.columns:
                continue

            woe_expr = None
            for bin_def_entry in bins:
                bin_id = bin_def_entry["bin_id"]
                is_missing = bin_def_entry.get("is_missing_bin", False)

                if kind == "numeric":
                    lower = bin_def_entry.get("lower")
                    upper = bin_def_entry.get("upper")
                    lower_inc = bin_def_entry.get("lower_inclusive", False)
                    upper_inc = bin_def_entry.get("upper_inclusive", True)
                    if is_missing:
                        mask_expr = pl.col(variable).is_null()
                    else:
                        c = pl.col(variable)
                        parts = []
                        if lower is not None:
                            parts.append((c >= lower) if lower_inc else (c > lower))
                        if upper is not None:
                            parts.append((c <= upper) if upper_inc else (c < upper))
                        mask_expr = parts[0]
                        for p in parts[1:]:
                            mask_expr = mask_expr & p
                else:
                    categories = bin_def_entry.get("categories", [])
                    if is_missing:
                        mask_expr = pl.col(variable).is_null()
                    elif bin_def_entry.get("is_other_bin", False):
                        explicit_cats = []
                        for bd in bins:
                            if bd.get("is_missing_bin", False) or bd.get("is_other_bin", False):
                                continue
                            explicit_cats.extend(bd.get("categories") or [])
                        mask_expr = pl.col(variable).is_not_null() & ~pl.col(variable).is_in(explicit_cats)
                    elif categories:
                        mask_expr = pl.col(variable).is_in(categories)
                    else:
                        mask_expr = pl.lit(False)

                woe_val = woe_map.get(variable, {}).get(bin_id, 0.0)
                when_clause = pl.when(mask_expr).then(pl.lit(woe_val))
                woe_expr = when_clause if woe_expr is None else woe_expr.when(mask_expr).then(pl.lit(woe_val))

            if woe_expr is None:
                raise ValueError(f"WOE transform: variable '{variable}' has no bins defined")

            woe_expr = woe_expr.otherwise(pl.lit(None, dtype=pl.Float64))
            result_df = result_df.with_columns(woe_expr.alias(woe_col))

            unmatched = result_df.filter(pl.col(woe_col).is_null()).height
            if unmatched > 0:
                raise ValueError(
                    f"WOE transform: {unmatched} row(s) in variable '{variable}' "
                    f"did not match any bin. All training rows must belong to a defined bin."
                )

            woe_columns.append(woe_col)

        transform_report = {
            "target_column": target_column,
            "transformed_variables": woe_columns,
            "selected_only": selected_names is not None,
            "row_count": df.height,
        }
        report_artifact_ref = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-transform-report-{context.step_spec.step_id}",
            payload=transform_report,
            metadata={},
        )

        dataset_artifact = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem=f"woe-transformed-train-{context.step_spec.step_id}",
            frame=result_df,
            metadata={
                "source_artifact_id": train_artifact.artifact_id,
                "woe_columns": woe_columns,
                "target_column": target_column,
            },
        )

        all_outputs = [dataset_artifact, report_artifact_ref]
        return NodeOutput(
            artifacts=all_outputs,
            metrics={"variable_count": len(woe_columns)})


class LogisticRegressionNode(NodeType):
    node_type = "cardre.logistic_regression"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["model"]

    VALID_PENALTIES = {"l1", "l2", "elasticnet", None}
    VALID_SOLVERS = {"lbfgs", "liblinear", "newton-cg", "newton-cholesky", "sag", "saga"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        penalty = params.get("penalty")
        if penalty is not None and penalty not in self.VALID_PENALTIES:
            errors.append(f"penalty must be one of {self.VALID_PENALTIES}, got '{penalty}'")
        solver = params.get("solver", "lbfgs")
        if solver not in self.VALID_SOLVERS:
            errors.append(f"solver must be one of {self.VALID_SOLVERS}, got '{solver}'")
        C = params.get("C", 1.0)
        try:
            if float(C) <= 0:
                errors.append("C must be positive")
        except (ValueError, TypeError):
            errors.append("C must be a number")
        max_iter = params.get("max_iter", 1000)
        try:
            if int(max_iter) < 1:
                errors.append("max_iter must be >= 1")
        except (ValueError, TypeError):
            errors.append("max_iter must be an integer")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        import numpy as np
        from sklearn.linear_model import LogisticRegression as SkLearnLR

        store = context.store
        params = context.validated_params
        reader = ArtifactEvidenceReader(store)
        train_artifact = next(a for a in context.input_artifacts if a.role == "train")

        meta = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)

        target_column = meta.target_column
        good_values = set(str(v) for v in meta.good_values)
        bad_values = set(str(v) for v in meta.bad_values)

        if not target_column:
            raise ValueError("Target column is required for logistic regression")
        if not good_values:
            raise ValueError("Good values must be defined for logistic regression")
        if not bad_values:
            raise ValueError("Bad values must be defined for logistic regression")

        df = pl.read_parquet(store.artifact_path(train_artifact))
        woe_cols = [c for c in df.columns if c.endswith("_woe")]
        if not woe_cols:
            raise ValueError("No WOE-transformed columns found in training data")

        X = df.select(woe_cols).to_numpy()

        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in training data")

        raw_target = df[target_column].cast(pl.String)
        y = raw_target.to_list()
        all_known = good_values | bad_values
        unknown = [str(v) for v in y if str(v) not in all_known]
        if unknown:
            unique_unknown = sorted(set(unknown))
            raise ValueError(
                f"Target column '{target_column}' contains {len(unknown)} value(s) "
                f"not declared as good or bad: {unique_unknown[:10]}. "
                f"Every row must be explicitly classified."
            )

        y_binary = [1 if str(v) in bad_values else 0 for v in y]
        n_bad = sum(y_binary)
        n_good = len(y_binary) - n_bad
        if n_bad == 0:
            raise ValueError(f"Logistic regression: no bad-class rows found (bad_values={sorted(bad_values)})")
        if n_good == 0:
            raise ValueError(f"Logistic regression: no good-class rows found (good_values={sorted(good_values)})")

        penalty = params.get("penalty")
        C = float(params.get("C", 1.0))
        max_iter = int(params.get("max_iter", 1000))
        solver = str(params.get("solver", "lbfgs"))
        random_seed = int(params.get("random_seed", 42))

        lr_params = {"C": C, "max_iter": max_iter, "solver": solver, "random_state": random_seed}
        if penalty is not None:
            lr_params["penalty"] = penalty

        lr = SkLearnLR(**lr_params)
        lr.fit(X, y_binary)

        bad_class = sorted(bad_values)[0] if bad_values else "1"
        good_class = sorted(good_values)[0] if good_values else "0"
        class_map = {idx: label for idx, label in enumerate(lr.classes_)}
        bad_class_idx = 1 if len(lr.classes_) > 1 else 0
        if bad_class_idx == 0:
            class_mapping = {"good": str(good_class), "bad": str(bad_class)}
        else:
            class_mapping = {"good": str(good_class), "bad": str(bad_class)}

        features_list = woe_cols
        coefficients = {col: round(float(coef), 6) for col, coef in zip(features_list, lr.coef_[0])}

        warnings_list: list[dict] = []
        if not lr.n_iter_[0] < max_iter:
            warnings_list.append({
                "code": "CONVERGENCE_FAILURE",
                "message": f"Logistic regression did not converge after {max_iter} iterations",
            })

        converged = bool(lr.n_iter_[0] < max_iter)
        training_params = {}
        for k, v in lr_params.items():
            if isinstance(v, np.bool_):
                training_params[k] = bool(v)
            elif isinstance(v, np.integer):
                training_params[k] = int(v)
            elif isinstance(v, np.floating):
                training_params[k] = float(v)
            else:
                training_params[k] = v

        prob_col_idx = 1
        for idx, cls_label in enumerate(lr.classes_):
            if str(cls_label) == str(bad_class):
                prob_col_idx = idx
                break

        feature_order_hash = json_logical_hash(
            {"features": features_list}
        )

        model = {
            "schema_version": "cardre.model_artifact.v1",
            "model_family": "logistic_regression",
            "target_column": target_column,
            "features": features_list,
            "intercept": round(float(lr.intercept_[0]), 6),
            "coefficients": coefficients,
            "class_mapping": class_mapping,
            "bad_class_label": str(bad_class),
            "target_event_value": str(bad_class),
            "probability_column_index": prob_col_idx,
            "feature_contract": {
                "features": features_list,
                "transformation_strategy": "woe",
                "order_hash": feature_order_hash,
                "missing_policy": "error",
                "unknown_category_policy": "error",
            },
            "feature_order_hash": feature_order_hash,
            "training": {
                "row_count": X.shape[0],
                "converged": converged,
                "iterations": int(lr.n_iter_[0]),
                "params": training_params,
            },
            "warnings": warnings_list,
        }

        artifact = write_json_artifact(
            store, artifact_type="model", role="model",
            stem=f"logistic-model-{context.step_spec.step_id}",
            payload=model,
            metadata={
                "feature_count": len(features_list),
                "target_column": target_column,
                "schema_version": SCHEMA_MODEL_ARTIFACT,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"feature_count": len(features_list), "converged": lr.n_iter_[0] < max_iter})


class ScoreScalingNode(NodeType):
    node_type = "cardre.score_scaling"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["model", "definition", "report"]
    output_roles: list[str] = ["scorecard"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        base_odds = params.get("base_odds", 50.0)
        try:
            if float(base_odds) <= 0:
                errors.append("base_odds must be positive")
        except (ValueError, TypeError):
            errors.append("base_odds must be a number")
        pdo = params.get("points_to_double_odds", 20)
        try:
            if float(pdo) <= 0:
                errors.append("points_to_double_odds must be positive")
        except (ValueError, TypeError):
            errors.append("points_to_double_odds must be a number")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        import math

        store = context.store
        params = context.validated_params
        model_artifact = next(a for a in context.input_artifacts if a.role == "model")

        bin_artifacts = []
        woe_report_artifacts = []
        meta_artifacts = []
        for a in context.input_artifacts:
            if a.role == "definition":
                try:
                    payload = json.loads(store.artifact_path(a).read_text())
                    if "variables" in payload and "selected" not in payload:
                        bin_artifacts.append(a)
                    elif "target_column" in payload and "good_values" in payload and "bad_values" in payload:
                        meta_artifacts.append(a)
                except Exception:
                    continue
            elif a.role == "report":
                try:
                    content = store.artifact_path(a).read_bytes()
                    if content[:4] != b"PAR1":
                        continue
                    temp = pl.read_parquet(store.artifact_path(a))
                    if "woe" in temp.columns and "bin_id" in temp.columns and "variable" in temp.columns:
                        woe_report_artifacts.append(a)
                except Exception:
                    continue

        if len(bin_artifacts) != 1:
            raise ValueError(f"Score scaling requires exactly one bin definition artifact; found {len(bin_artifacts)}")
        if len(woe_report_artifacts) != 1:
            raise ValueError(f"Score scaling requires exactly one WOE report artifact; found {len(woe_report_artifacts)}")
        if len(meta_artifacts) > 1:
            raise ValueError(f"Score scaling requires at most one modelling metadata artifact; found {len(meta_artifacts)}")
        bin_artifact = bin_artifacts[0]
        woe_report_artifact = woe_report_artifacts[0]

        model = json.loads(store.artifact_path(model_artifact).read_text())
        bin_def = json.loads(store.artifact_path(bin_artifact).read_text())

        if not bin_def.get("variables"):
            raise ValueError("Score scaling received an empty bin definition")

        base_score = float(params.get("base_score", 600))
        base_odds = float(params.get("base_odds", 50.0))
        pdo = float(params.get("points_to_double_odds", 20))
        higher_is_lower_risk = bool(params.get("higher_score_is_lower_risk", True))

        if base_odds <= 0:
            raise ValueError(f"base_odds must be positive, got {base_odds}")
        if pdo <= 0:
            raise ValueError(f"points_to_double_odds must be positive, got {pdo}")

        factor = pdo / math.log(2)
        offset = base_score - factor * math.log(base_odds)
        intercept = float(model.get("intercept", 0))
        coefficients = model.get("coefficients", {})

        direction = -1.0 if higher_is_lower_risk else 1.0
        # Score = offset + direction * factor * (intercept + sum(coef_i * woe_i))
        #       = base_points + sum(attribute_points_i)
        # where:
        #   base_points = offset + direction * factor * intercept
        #   attribute_points_i = direction * factor * coef_i * woe_i
        base_points = round(offset + direction * factor * intercept, 2)

        attributes: list[dict] = []
        all_woe_map: dict[str, dict[str, float]] = {}
        if woe_report_artifact:
            woe_df = pl.read_parquet(store.artifact_path(woe_report_artifact))
            for row in woe_df.iter_rows():
                cols = woe_df.columns
                var = str(row[cols.index("variable")])
                bin_id = str(row[cols.index("bin_id")])
                woe_val = float(row[cols.index("woe")])
                if var not in all_woe_map:
                    all_woe_map[var] = {}
                all_woe_map[var][bin_id] = woe_val

        for var_def in bin_def.get("variables", []):
            variable = var_def["variable"]
            woe_key = f"{variable}_woe"
            if woe_key not in coefficients:
                continue
            coef = float(coefficients[woe_key])

            for bin_entry in var_def.get("bins", []):
                bin_id = bin_entry["bin_id"]
                label = bin_entry["label"]
                woe_val = all_woe_map.get(variable, {}).get(bin_id)
                if woe_val is None:
                    raise ValueError(
                        f"Score scaling: missing WOE value for variable {variable!r} bin {bin_id!r}"
                    )
                raw_points = direction * factor * coef * woe_val
                point_value = round(raw_points, 2)
                attributes.append({
                    "variable": variable,
                    "bin_id": bin_id,
                    "label": label,
                    "woe": round(woe_val, 6),
                    "coefficient": coef,
                    "points": point_value,
                })

        scorecard = {
            "base_score": base_score,
            "base_odds": base_odds,
            "points_to_double_odds": pdo,
            "factor": round(factor, 6),
            "offset": round(offset, 6),
            "higher_score_is_lower_risk": higher_is_lower_risk,
            "intercept": intercept,
            "base_points": base_points,
            "attributes": attributes,
            "target_column": model.get("target_column", ""),
        }

        scorecard["schema_version"] = SCHEMA_SCORE_SCALING
        artifact = write_json_artifact(
            store, artifact_type="scorecard", role="scorecard",
            stem=f"scorecard-{context.step_spec.step_id}",
            payload=scorecard,
            metadata={
                "base_score": base_score,
                "attribute_count": len(attributes),
                "schema_version": SCHEMA_SCORE_SCALING,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"attribute_count": len(attributes)})


class BuildSummaryReportNode(NodeType):
    node_type = "cardre.build_summary_report"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["scorecard", "model", "report"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        scorecard_artifact = next(a for a in context.input_artifacts if a.role == "scorecard")
        model_artifact = next(a for a in context.input_artifacts if a.role == "model")
        woe_report_artifacts = [a for a in context.input_artifacts if a.role == "report"]

        scorecard = json.loads(store.artifact_path(scorecard_artifact).read_text())
        model = json.loads(store.artifact_path(model_artifact).read_text())

        woe_summaries = []
        for a in woe_report_artifacts:
            try:
                content = store.artifact_path(a).read_bytes()
                if content[:4] == b"PAR1":
                    woe_df = pl.read_parquet(store.artifact_path(a))
                    if "iv" in woe_df.columns:
                        woe_summaries.append({
                            "artifact_id": a.artifact_id,
                            "type": "iv_ranking",
                            "row_count": woe_df.height,
                            "columns": woe_df.columns,
                        })
                    elif "woe" in woe_df.columns:
                        woe_summaries.append({
                            "artifact_id": a.artifact_id,
                            "type": "woe_table",
                            "row_count": woe_df.height,
                            "columns": woe_df.columns,
                        })
            except Exception:
                pass

        report = {
            "model_summary": {
                "target_column": model.get("target_column", ""),
                "features": model.get("features", []),
                "intercept": model.get("intercept", 0),
                "coefficient_count": len(model.get("coefficients", {})),
                "converged": model.get("training", {}).get("converged", False),
                "row_count": model.get("training", {}).get("row_count", 0),
            },
            "scorecard_summary": {
                "base_score": scorecard.get("base_score", 0),
                "base_odds": scorecard.get("base_odds", 0),
                "points_to_double_odds": scorecard.get("points_to_double_odds", 0),
                "attribute_count": len(scorecard.get("attributes", [])),
                "higher_score_is_lower_risk": scorecard.get("higher_score_is_lower_risk", True),
            },
            "woe_iv_references": woe_summaries,
            "warnings": model.get("warnings", []),
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"build-summary-{context.step_spec.step_id}",
            payload=report,
            metadata={},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"feature_count": len(model.get("features", []))})


class DummyFitNode(NodeType):
    node_type = "cardre.dummy_fit"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        input_artifact = context.input_artifacts[0]
        params = context.validated_params

        df = pl.read_parquet(store.artifact_path(input_artifact))
        dummy_def = {
            "model_type": "dummy",
            "version": self.version,
            "params": params,
            "input_columns": list(df.columns),
            "row_count": df.height,
        }

        artifact = write_json_artifact(
            store,
            artifact_type="definition",
            role="definition",
            stem=f"dummy-fit-{context.step_spec.step_id}",
            payload=dummy_def,
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height})


def validate_manual_binning_overrides(
    bin_def: dict, overrides: list[dict], selected_vars: set[str] | None = None
) -> list[str]:
    """Validate overrides against fine-classing bin definitions.

    Checks that each override references a real variable, uses a supported
    action, has a reason, mentions only existing bin IDs, and for numeric
    merge_bins the source bins are adjacent in the original ordering.

    When *selected_vars* is provided, rejects overrides for variables that
    are not in the selected-variables set.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    var_map = {v["variable"]: v for v in bin_def.get("variables", [])}

    for i, override in enumerate(overrides):
        prefix = f"overrides[{i}]"
        variable = override.get("variable", "")
        action = override.get("action", "")
        reason = override.get("reason", "")
        source_bin_ids = override.get("source_bin_ids", [])

        if not reason:
            errors.append(f"{prefix}: override for '{variable}' requires a non-empty reason")
            continue
        if variable not in var_map:
            errors.append(f"{prefix}: references unknown variable '{variable}'")
            continue
        if selected_vars is not None and variable not in selected_vars:
            errors.append(
                f"{prefix}: variable '{variable}' was not selected by variable-selection "
                f"and cannot accept manual binning overrides"
            )
            continue
        if action not in ("merge_bins", "group_categories", "isolate_missing", "isolate_special_value"):
            errors.append(f"{prefix}: unsupported action '{action}'")
            continue

        var_bins = var_map[variable].get("bins", [])
        bin_id_map = {b["bin_id"]: b for b in var_bins}

        for bid in source_bin_ids:
            if bid not in bin_id_map:
                errors.append(f"{prefix}: bin_id '{bid}' not found in variable '{variable}'")

        if errors:
            continue

        if action == "merge_bins":
            if len(source_bin_ids) < 2:
                errors.append(f"{prefix}: merge_bins requires at least 2 source bins")
                continue
            kind = var_map[variable].get("kind", "")
            if kind == "numeric":
                bin_positions = [var_bins.index(bin_id_map[bid]) for bid in source_bin_ids]
                expected_positions = list(range(min(bin_positions), max(bin_positions) + 1))
                if bin_positions != expected_positions:
                    errors.append(
                        f"{prefix}: numeric bin merge requires adjacent bins. "
                        f"Source bins at positions {bin_positions} are not contiguous."
                    )

    return errors


def apply_manual_binning_overrides(
    bin_def: dict, overrides: list[dict], selected_vars: set[str] | None = None
) -> dict:
    """Apply manual binning overrides to a fine-classing bin definition.

    Returns a new ``bin_def`` dict with merged / grouped bins computed
    and (if *selected_vars* is given) filtered to the selected variables.
    Raises ``ValueError`` on invalid overrides — call
    :func:`validate_manual_binning_overrides` first for user-facing errors.
    """
    var_map = {v["variable"]: dict(v) for v in bin_def.get("variables", [])}
    warnings: list[dict] = []

    for override in overrides:
        variable = override.get("variable", "")
        action = override.get("action", "")
        source_bin_ids = override.get("source_bin_ids", [])

        if variable not in var_map:
            raise ValueError(f"Override references unknown variable '{variable}'")

        var_info = var_map[variable]
        var_bins = list(var_info.get("bins", []))
        bin_id_map = {b["bin_id"]: b for b in var_bins}

        if action == "merge_bins":
            merged = {
                "bin_id": f"{variable}_manual_{override.get('new_label', 'merged').lower().replace(' ', '_')}",
                "label": override.get("new_label", "Merged"),
                "lower": bin_id_map[source_bin_ids[0]].get("lower"),
                "upper": bin_id_map[source_bin_ids[-1]].get("upper"),
                "lower_inclusive": bin_id_map[source_bin_ids[0]].get("lower_inclusive", False),
                "upper_inclusive": bin_id_map[source_bin_ids[-1]].get("upper_inclusive", True),
                "categories": None,
                "is_missing_bin": False,
                "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
            }
            new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
            insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
            new_bins.insert(insert_pos, merged)
            var_info["bins"] = new_bins

        elif action == "group_categories":
            grouped = {
                "bin_id": f"{variable}_manual_grouped",
                "label": override.get("new_label", "Grouped"),
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": sum([bin_id_map[bid].get("categories", []) for bid in source_bin_ids], []),
                "is_missing_bin": False,
                "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
            }
            new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
            insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
            new_bins.insert(insert_pos, grouped)
            var_info["bins"] = new_bins

    if selected_vars is not None:
        var_map = {k: v for k, v in var_map.items() if k in selected_vars}

    if not overrides:
        warnings.append({"message": "No manual overrides applied; passing through auto bins for selected variables"})

    return {
        "variables": list(var_map.values()),
        "warnings": bin_def.get("warnings", []) + warnings,
    }