from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType
from cardre.evidence import (
    AmbiguousEvidenceError,
    ArtifactEvidenceReader,
    EvidenceKind,
    EvidenceNotFoundError,
    SCHEMA_BIN_DEFINITION,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_WOE_TABLE,
)


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
        good_values_list = list(good_values)
        bad_values_list = list(bad_values)

        if not target_column or target_column not in df.columns:
            raise ValueError(f"WOE/IV target column {target_column!r} not found in training data")
        if not good_values or not bad_values:
            raise ValueError("WOE/IV requires non-empty good_values and bad_values")
        target_series = df[target_column].cast(pl.String)
        total_good_all = int(target_series.is_in(good_values_list).sum())
        total_bad_all = int(target_series.is_in(bad_values_list).sum())
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
                    bin_good = int(target_series.filter(bin_mask).is_in(good_values_list).sum())
                    bin_bad = int(target_series.filter(bin_mask).is_in(bad_values_list).sum())
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
            iv_df = iv_lf.dataframe.collect()
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
        woe_exprs = []
        column_variable_map: list[tuple[str, str]] = []
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
            woe_exprs.append(woe_expr.alias(woe_col))
            column_variable_map.append((woe_col, variable))
            woe_columns.append(woe_col)

        if woe_exprs:
            result_df = result_df.with_columns(woe_exprs)

        for woe_col, variable in column_variable_map:
            unmatched = result_df.filter(pl.col(woe_col).is_null()).height
            if unmatched > 0:
                raise ValueError(
                    f"WOE transform: {unmatched} row(s) in variable '{variable}' "
                    f"did not match any bin. All training rows must belong to a defined bin."
                )

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
