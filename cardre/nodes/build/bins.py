from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind, SCHEMA_BIN_DEFINITION


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

        sorted_vals = non_null[col].sort().to_list()
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


def validate_manual_binning_overrides(
    bin_def: dict, overrides: list[dict], selected_vars: set[str] | None = None
) -> list[str]:
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
