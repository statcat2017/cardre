from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.nodes._bin_mask import build_bin_condition
from cardre.evidence import (
    AmbiguousEvidenceError,
    ArtifactEvidenceReader,
    EvidenceKind,
    EvidenceNotFoundError,
    SCHEMA_BIN_DEFINITION,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
    SCHEMA_WOE_TABLE,
)


class CalculateWoeIvNode(NodeType):
    node_type = "cardre.calculate_woe_iv"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Calculate WOE & IV",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="zero_cell_policy",
                            label="Zero Cell Policy",
                            kind="string",
                            default="block",
                            constraint=ParameterConstraint(enum_values=["block"]),
                            help_text="Policy for handling zero-cell bins in final WOE calculation",
                        ),
                        ParameterDefinition(
                            name="purpose",
                            label="Purpose",
                            kind="enum",
                            default="initial",
                            constraint=ParameterConstraint(enum_values=["initial", "final"]),
                            help_text="Calculation purpose: initial exploratory or final production",
                        ),
                        ParameterDefinition(
                            name="smoothing",
                            label="Smoothing",
                            kind="object",
                            default=None,
                            required=False,
                            help_text="Optional additive smoothing configuration with method, alpha, and rationale",
                        ),
                    ],
                ),
            ],
        )

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

                bin_mask = build_bin_condition(bin_def, col_values, kind, bins, variable=variable, bin_id=bin_id)

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

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Variable Clustering",
            methods=[
                MethodOption(
                    id="correlation_threshold",
                    label="Correlation Threshold",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="similarity_metric", label="Similarity Metric",
                            kind="enum", default="pearson",
                            constraint=ParameterConstraint(enum_values=["pearson", "spearman"]),
                            help_text="Correlation metric for pairwise similarity",
                        ),
                        ParameterDefinition(
                            name="absolute_correlation", label="Absolute Correlation",
                            kind="boolean", default=True,
                            help_text="Use absolute value of correlation before thresholding",
                        ),
                        ParameterDefinition(
                            name="threshold", label="Threshold",
                            kind="float", default=0.7,
                            constraint=ParameterConstraint(exclusive_min=0.0, exclusive_max=1.0),
                            help_text="Correlation threshold for cluster formation",
                        ),
                        ParameterDefinition(
                            name="input_representation", label="Input Representation",
                            kind="enum", default="raw_train",
                            constraint=ParameterConstraint(enum_values=["raw_train", "woe_train"]),
                            help_text="Variable representation for clustering",
                        ),
                        ParameterDefinition(
                            name="missing_handling", label="Missing Handling",
                            kind="enum", default="pairwise",
                            constraint=ParameterConstraint(enum_values=["pairwise", "complete_case"]),
                            help_text="How to handle missing values in correlation computation",
                        ),
                        ParameterDefinition(
                            name="candidate_limit", label="Candidate Limit",
                            kind="integer", default=50,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of candidate variables to consider",
                        ),
                        ParameterDefinition(
                            name="representative_rule", label="Representative Rule",
                            kind="enum", default="highest_iv",
                            constraint=ParameterConstraint(enum_values=["highest_iv", "lowest_missing", "manual"]),
                            help_text="Rule for selecting cluster representative",
                        ),
                    ],
                ),
                MethodOption(
                    id="hierarchical",
                    label="Hierarchical Correlation",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="similarity_metric", label="Similarity Metric",
                            kind="enum", default="pearson",
                            constraint=ParameterConstraint(enum_values=["pearson", "spearman"]),
                            help_text="Correlation metric for pairwise similarity",
                        ),
                        ParameterDefinition(
                            name="linkage", label="Linkage",
                            kind="enum", default="average",
                            constraint=ParameterConstraint(enum_values=["average", "complete"]),
                            help_text="Linkage criterion for hierarchical clustering",
                        ),
                        ParameterDefinition(
                            name="cut_threshold", label="Cut Threshold",
                            kind="float", default=0.3,
                            constraint=ParameterConstraint(exclusive_min=0.0),
                            help_text="Distance threshold for cutting the dendrogram",
                        ),
                        ParameterDefinition(
                            name="input_representation", label="Input Representation",
                            kind="enum", default="raw_train",
                            constraint=ParameterConstraint(enum_values=["raw_train", "woe_train"]),
                            help_text="Variable representation for clustering",
                        ),
                        ParameterDefinition(
                            name="missing_handling", label="Missing Handling",
                            kind="enum", default="pairwise",
                            constraint=ParameterConstraint(enum_values=["pairwise", "complete_case"]),
                            help_text="How to handle missing values in correlation computation",
                        ),
                        ParameterDefinition(
                            name="candidate_limit", label="Candidate Limit",
                            kind="integer", default=50,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of candidate variables to consider",
                        ),
                        ParameterDefinition(
                            name="representative_rule", label="Representative Rule",
                            kind="enum", default="highest_iv",
                            constraint=ParameterConstraint(enum_values=["highest_iv", "lowest_missing", "manual"]),
                            help_text="Rule for selecting cluster representative",
                        ),
                    ],
                ),
                MethodOption(id="varclus_pca", label="VARCLUS / PCA (coming soon)", status="coming_soon", params=[]),
                MethodOption(id="mixed_type", label="Mixed-Type (coming soon)", status="coming_soon", params=[]),
                MethodOption(id="target_aware", label="Target-Aware (coming soon)", status="coming_soon", params=[]),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        method = params.get("method", "correlation_threshold")
        if method == "correlation_threshold":
            threshold = params.get("threshold", params.get("correlation_threshold", 0.7))
            try:
                if not (0 < float(threshold) < 1):
                    errors.append("threshold must be between 0 and 1 (exclusive)")
            except (ValueError, TypeError):
                errors.append("threshold must be a number")
        return errors

    def _build_woe_columns(
        self, df: pl.DataFrame, bin_def: Any, woe_table: Any,
    ) -> list[pl.Expr]:
        from cardre.nodes._bin_mask import build_bin_condition

        woe_exprs: list[pl.Expr] = []
        for var_def in bin_def.variables:
            variable = var_def.variable
            kind = var_def.kind
            bins = var_def.bins

            if variable not in df.columns:
                continue
            if not df.schema[variable].is_numeric():
                continue

            woe_expr = None
            for bin_entry in bins:
                bin_id = bin_entry["bin_id"]
                woe_val = woe_table.mapping.get(variable, {}).get(bin_id)
                if woe_val is None:
                    continue
                mask_expr = build_bin_condition(
                    bin_entry, pl.col(variable), kind, bins,
                    variable=variable, bin_id=bin_id,
                )
                when_clause = pl.when(mask_expr).then(pl.lit(woe_val))
                woe_expr = when_clause if woe_expr is None else woe_expr.when(mask_expr).then(pl.lit(woe_val))

            if woe_expr is not None:
                woe_expr = woe_expr.otherwise(pl.lit(None, dtype=pl.Float64))
                woe_exprs.append(woe_expr.alias(f"{variable}_woe"))

        return woe_exprs

    def _compute_correlation_matrix(
        self, df: pl.DataFrame, columns: list[str],
        method: str, missing_handling: str,
        absolute: bool,
    ) -> pl.DataFrame:
        import numpy as np

        # Select candidate columns
        matrix_df = df.select(columns)

        if missing_handling == "complete_case":
            matrix_df = matrix_df.drop_nulls()

        arr = matrix_df.to_numpy()
        if arr.shape[1] < 2:
            n = arr.shape[1]
            corr = np.eye(n)
        elif method == "spearman":
            ranks = np.argsort(np.argsort(arr, axis=0), axis=0).astype(float)
            corr = np.corrcoef(ranks.T)
        else:
            corr = np.corrcoef(arr.T)

        corr = np.nan_to_num(corr, nan=0.0)

        if absolute:
            corr = np.abs(corr)

        return pl.DataFrame(corr, schema=columns, orient="row").with_row_index("_col")

    def _correlation_threshold_clusters(
        self, df: pl.DataFrame, columns: list[str],
        corr_matrix: pl.DataFrame, threshold: float,
        iv_map: dict[str, float], missing_map: dict[str, float],
        representative_rule: str,
    ) -> tuple[list[dict], list[str], list[dict]]:
        import numpy as np

        arr = corr_matrix.drop("_col").to_numpy()
        n = len(columns)
        adj: dict[int, set[int]] = {i: set() for i in range(n)}
        for i in range(n):
            for j in range(i + 1, n):
                if arr[i, j] >= threshold:
                    adj[i].add(j)
                    adj[j].add(i)

        visited: set[int] = set()
        cluster_list: list[list[int]] = []
        for i in range(n):
            if i in visited:
                continue
            component: list[int] = []
            stack = [i]
            while stack:
                v = stack.pop()
                if v in visited:
                    continue
                visited.add(v)
                component.append(v)
                for nb in adj[v]:
                    if nb not in visited:
                        stack.append(nb)
            cluster_list.append(component)

        clusters_out: list[dict] = []
        singletons: list[str] = []
        warnings_list: list[dict] = []

        for cid, members in enumerate(cluster_list, 1):
            var_names = [columns[m] for m in members]
            if len(var_names) == 1:
                singletons.append(var_names[0])
                continue

            max_corr = 0.0
            for i in members:
                for j in members:
                    if i < j and arr[i, j] > max_corr:
                        max_corr = arr[i, j]

            rep = self._pick_representative(
                var_names, iv_map, missing_map, representative_rule,
            )

            enriched_members = []
            for vn in var_names:
                enriched_members.append({
                    "variable": vn,
                    "iv": iv_map.get(vn),
                    "missing_rate": missing_map.get(vn),
                })

            clusters_out.append({
                "cluster_id": f"cluster_{cid:03d}",
                "variables": enriched_members,
                "representative_suggestion": rep["variable"],
                "representative_reason": rep["reason"],
                "max_pairwise_abs_corr": round(max_corr, 4),
                "notes": [],
            })

        return clusters_out, singletons, warnings_list

    def _hierarchical_clusters(
        self, df: pl.DataFrame, columns: list[str],
        corr_matrix: pl.DataFrame, linkage: str, cut_threshold: float,
        iv_map: dict[str, float], missing_map: dict[str, float],
        representative_rule: str,
    ) -> tuple[list[dict], list[str], list[dict]]:
        import numpy as np

        arr = 1.0 - corr_matrix.drop("_col").to_numpy()
        n = len(columns)
        np.fill_diagonal(arr, 0.0)

        # Agglomerative clustering
        clusters: list[list[int]] = [[i] for i in range(n)]
        distances: dict[tuple[int, int], float] = {}

        def cluster_distance(c1: list[int], c2: list[int]) -> float:
            if linkage == "complete":
                return max(arr[i, j] for i in c1 for j in c2)
            else:
                return sum(arr[i, j] for i in c1 for j in c2) / (len(c1) * len(c2))

        while len(clusters) > 1:
            best_i, best_j, best_d = -1, -1, float("inf")
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    d = cluster_distance(clusters[i], clusters[j])
                    if d < best_d:
                        best_d, best_i, best_j = d, i, j

            if best_d > cut_threshold:
                break

            merged = clusters[best_i] + clusters[best_j]
            clusters = [c for k, c in enumerate(clusters) if k not in (best_i, best_j)]
            clusters.append(merged)

        clusters_out: list[dict] = []
        singletons: list[str] = []
        warnings_list: list[dict] = []

        arr_sim = 1.0 - arr
        for cid, members in enumerate(clusters, 1):
            var_names = [columns[m] for m in members]
            if len(var_names) == 1:
                singletons.append(var_names[0])
                continue

            max_corr = 0.0
            for i in members:
                for j in members:
                    if i < j and arr_sim[i, j] > max_corr:
                        max_corr = arr_sim[i, j]

            rep = self._pick_representative(
                var_names, iv_map, missing_map, representative_rule,
            )

            enriched_members = []
            for vn in var_names:
                enriched_members.append({
                    "variable": vn,
                    "iv": iv_map.get(vn),
                    "missing_rate": missing_map.get(vn),
                })

            clusters_out.append({
                "cluster_id": f"cluster_{cid:03d}",
                "variables": enriched_members,
                "representative_suggestion": rep["variable"],
                "representative_reason": rep["reason"],
                "max_pairwise_abs_corr": round(max_corr, 4),
                "notes": [],
            })

        return clusters_out, singletons, warnings_list

    def _pick_representative(
        self, variables: list[str],
        iv_map: dict[str, float], missing_map: dict[str, float],
        rule: str,
    ) -> dict[str, str]:
        if rule == "manual":
            return {"variable": "", "reason": "manual review required"}

        if rule == "lowest_missing":
            best = min(variables, key=lambda v: missing_map.get(v, float("inf")))
            return {"variable": best, "reason": "lowest missing rate"}

        # highest_iv (default)
        best = max(variables, key=lambda v: iv_map.get(v, 0.0))
        return {"variable": best, "reason": "highest IV"}

    def run(self, context: ExecutionContext) -> NodeOutput:
        import numpy as np

        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params

        method = params.get("method", "correlation_threshold")
        similarity_metric = params.get("similarity_metric", "pearson")
        absolute_correlation = params.get("absolute_correlation", True)
        candidate_limit = int(params.get("candidate_limit", 50))
        missing_handling = params.get("missing_handling", "pairwise")
        representative_rule = params.get("representative_rule", "highest_iv")

        if method == "correlation_threshold":
            threshold = float(params.get("threshold", params.get("correlation_threshold", 0.7)))
        elif method == "hierarchical":
            threshold = float(params.get("cut_threshold", 0.3))
            linkage = params.get("linkage", "average")
        else:
            raise ValueError(f"Unknown or unavailable clustering method: {method!r}")

        input_representation = params.get("input_representation", "raw_train")

        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        df = pl.read_parquet(store.artifact_path(train_artifact))

        # Read IV table for variable ranking and representative suggestions
        iv_map: dict[str, float] = {}
        try:
            iv_table = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        except Exception:
            iv_table = None

        if iv_table is not None:
            try:
                iv_df = iv_table.dataframe.collect()
                for row in iv_df.iter_rows():
                    iv_map[str(row[0])] = float(row[1])
            except Exception:
                iv_map = {}

        # Compute missing rates
        missing_map: dict[str, float] = {}
        for col in df.columns:
            n_null = df[col].null_count()
            missing_map[col] = n_null / df.height if df.height > 0 else 0.0

        # Determine candidate variables
        numeric_cols = [c for c in df.columns if df.schema[c].is_numeric()]

        # If we have IV map, use that as candidate source (preferred)
        if iv_map:
            candidates = [c for c in numeric_cols if c in iv_map]
            candidates = sorted(candidates, key=lambda c: iv_map.get(c, 0.0), reverse=True)
        else:
            candidates = numeric_cols

        candidates = candidates[:candidate_limit]

        clusters_out: list[dict] = []
        singleton_variables: list[str] = []
        warnings_list: list[dict] = []

        if len(candidates) < 2:
            for col in candidates:
                singleton_variables.append(col)
            if candidates:
                warnings_list.append({
                    "message": f"Only {len(candidates)} numeric candidate(s); clustering is pass-through",
                })
        else:
            try:
                if input_representation == "woe_train":
                    bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
                    woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)
                    woe_exprs = self._build_woe_columns(df, bin_def, woe_table)
                    if woe_exprs:
                        woe_df = df.with_columns(woe_exprs)
                        woe_cols = [e.meta.output_name for e in woe_exprs]
                        woe_cols = [c for c in woe_cols if c.replace("_woe", "") in candidates]
                        woe_cols = woe_cols[:candidate_limit]
                        if len(woe_cols) < 2:
                            for col in candidates:
                                singleton_variables.append(col)
                            warnings_list.append({
                                "message": "Fewer than 2 WOE-transformed columns available; using singleton pass-through",
                            })
                        else:
                            corr_matrix = self._compute_correlation_matrix(
                                woe_df, woe_cols, similarity_metric, missing_handling, absolute_correlation,
                            )
                            woe_candidate_map = {c: c.replace("_woe", "") for c in woe_cols}
                            iv_map_woe = {wc: iv_map.get(oc, 0.0) for wc, oc in woe_candidate_map.items()}
                            missing_map_woe = {wc: missing_map.get(oc, 0.0) for wc, oc in woe_candidate_map.items()}

                            if method == "hierarchical":
                                clusters_out, singleton_variables, warnings_list = self._hierarchical_clusters(
                                    woe_df, woe_cols, corr_matrix, linkage, threshold,
                                    iv_map_woe, missing_map_woe, representative_rule,
                                )
                            else:
                                clusters_out, singleton_variables, warnings_list = self._correlation_threshold_clusters(
                                    woe_df, woe_cols, corr_matrix, threshold,
                                    iv_map_woe, missing_map_woe, representative_rule,
                                )

                            # Map WOE column names back to original variable names
                            for cl in clusters_out:
                                mapped_vars = []
                                for mv in cl["variables"]:
                                    orig = mv["variable"].replace("_woe", "")
                                    mapped_vars.append({
                                        "variable": orig,
                                        "iv": mv["iv"],
                                        "missing_rate": mv["missing_rate"],
                                    })
                                cl["variables"] = mapped_vars
                                if cl.get("representative_suggestion"):
                                    cl["representative_suggestion"] = cl["representative_suggestion"].replace("_woe", "")
                            singleton_variables = [v.replace("_woe", "") for v in singleton_variables]
                    else:
                        for col in candidates:
                            singleton_variables.append(col)
                        warnings_list.append({
                            "message": "No WOE-transformed columns could be built; using singleton pass-through on raw variables",
                        })
                else:
                    corr_matrix = self._compute_correlation_matrix(
                        df, candidates, similarity_metric, missing_handling, absolute_correlation,
                    )

                    if method == "hierarchical":
                        clusters_out, singleton_variables, warnings_list = self._hierarchical_clusters(
                            df, candidates, corr_matrix, linkage, threshold,
                            iv_map, missing_map, representative_rule,
                        )
                    else:
                        clusters_out, singleton_variables, warnings_list = self._correlation_threshold_clusters(
                            df, candidates, corr_matrix, threshold,
                            iv_map, missing_map, representative_rule,
                        )

            except ImportError:
                for col in candidates:
                    singleton_variables.append(col)
                warnings_list.append({"message": "Clustering unavailable (numpy not available); using singleton pass-through"})

        clustering_report = {
            "schema_version": SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
            "method": method,
            "input_representation": input_representation,
            "similarity_metric": similarity_metric,
            "absolute_correlation": absolute_correlation,
            "threshold": threshold,
            "missing_handling": missing_handling,
            "candidate_limit": candidate_limit,
            "representative_rule": representative_rule,
            "clusters": clusters_out,
            "singleton_variables": singleton_variables,
            "warnings": warnings_list,
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"clustering-{context.step_spec.step_id}",
            payload=clustering_report,
            metadata={
                "candidate_count": len(candidates),
                "cluster_count": len(clusters_out),
                "singleton_count": len(singleton_variables),
                "schema_version": SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={
                "candidate_count": len(candidates),
                "cluster_count": len(clusters_out),
                "singleton_count": len(singleton_variables),
                "warning_count": len(warnings_list),
            },
        )


class VariableSelectionNode(NodeType):
    node_type = "cardre.variable_selection"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["report"]
    output_roles: list[str] = ["definition"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Variable Selection",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="min_iv", label="Minimum IV",
                            kind="float", default=0.02,
                            constraint=ParameterConstraint(min_value=0.0),
                            help_text="Minimum Information Value threshold for variable inclusion",
                        ),
                        ParameterDefinition(
                            name="max_variables", label="Max Variables",
                            kind="integer", default=15,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of variables to select",
                        ),
                        ParameterDefinition(
                            name="manual_includes", label="Manual Includes",
                            kind="list", default=[], required=False,
                            help_text="List of dicts with 'variable' and 'reason' keys for forced inclusions",
                        ),
                        ParameterDefinition(
                            name="manual_excludes", label="Manual Excludes",
                            kind="list", default=[], required=False,
                            help_text="List of dicts with 'variable' and 'reason' keys for forced exclusions",
                        ),
                        ParameterDefinition(
                            name="cluster_representative_rule", label="Cluster Representative Rule",
                            kind="enum", default="none",
                            constraint=ParameterConstraint(
                                enum_values=["none", "highest_iv", "lowest_missing", "manual_override"],
                            ),
                            help_text="How to use variable clustering evidence for representative selection",
                        ),
                        ParameterDefinition(
                            name="cluster_representative_overrides", label="Cluster Representative Overrides",
                            kind="list", default=[], required=False,
                            help_text="List of dicts with 'cluster_id', 'variable', and 'reason' keys for manual override of cluster representatives",
                        ),
                    ],
                ),
            ],
        )

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

        overrides = list(params.get("cluster_representative_overrides", []))
        for entry in overrides:
            if not isinstance(entry, dict):
                errors.append("Each cluster_representative_override must be a dict")
                continue
            if not entry.get("cluster_id"):
                errors.append("cluster_representative_override missing 'cluster_id'")
            if not entry.get("variable"):
                errors.append("cluster_representative_override missing 'variable'")
            if not entry.get("reason"):
                errors.append(f"cluster_representative_override for '{entry.get('variable', '')}' missing 'reason'")

        return errors

    def _parse_cluster_variables(self, variables: list) -> list[str]:
        result: list[str] = []
        for v in variables:
            if isinstance(v, dict):
                result.append(str(v.get("variable", "")))
            else:
                result.append(str(v))
        return result

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params
        min_iv = float(params.get("min_iv", 0.02))
        max_variables = int(params.get("max_variables", 15))
        manual_entries_raw = list(params.get("manual_includes", []))
        manual_excludes_raw = list(params.get("manual_excludes", []))
        cluster_rule = params.get("cluster_representative_rule", "none")
        cluster_overrides_raw = list(params.get("cluster_representative_overrides", []))

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
        manual_includes = {v["variable"]: v["reason"] for v in manual_entries_raw}
        manual_excludes = {v["variable"]: v["reason"] for v in manual_excludes_raw}

        iv_lf = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        if iv_lf is not None:
            iv_df = iv_lf.dataframe.collect()
            iv_map: dict[str, float] = {}
            for row in iv_df.iter_rows():
                iv_map[str(row[0])] = float(row[1])
        else:
            iv_map = {}

        # Read clustering evidence
        clusters: list[dict[str, Any]] = []
        singleton_variables: list[str] = []
        clustering_evidence = None
        try:
            clustering_evidence = reader.find_optional(context.input_artifacts, EvidenceKind.VARIABLE_CLUSTERING)
        except Exception:
            clustering_evidence = None

        if clustering_evidence is not None:
            for cl in clustering_evidence.clusters:
                clusters.append({
                    "cluster_id": cl.cluster_id,
                    "variables": self._parse_cluster_variables(cl.variables),
                })
            singleton_variables = list(clustering_evidence.singleton_variables)
        else:
            # Legacy fallback: scan JSON reports for top-level "clusters"
            for a in context.input_artifacts:
                if a.role == "report" and a.media_type == "application/json":
                    try:
                        data = json.loads(store.artifact_path(a).read_text())
                        if "clusters" in data:
                            raw_clusters = data["clusters"]
                            for rc in raw_clusters:
                                clusters.append({
                                    "cluster_id": rc.get("cluster_id", ""),
                                    "variables": self._parse_cluster_variables(rc.get("variables", [])),
                                })
                            singleton_variables = list(data.get("singleton_variables", []))
                            break
                    except (json.JSONDecodeError, FileNotFoundError):
                        pass

        # Build cluster map: variable -> cluster_id
        cluster_map: dict[str, str] = {}
        for cl in clusters:
            for var in cl.get("variables", []):
                cluster_map[var] = cl["cluster_id"]

        # Build per-cluster ordered variable list (by IV descending)
        cluster_vars: dict[str, list[str]] = {}
        for cl in clusters:
            cid = cl["cluster_id"]
            vars_in_cluster = list(cl.get("variables", []))
            vars_in_cluster.sort(key=lambda v: iv_map.get(v, 0.0), reverse=True)
            cluster_vars[cid] = vars_in_cluster

        # Build override map
        cluster_overrides: dict[str, dict[str, str]] = {}
        for entry in cluster_overrides_raw:
            cid = entry["cluster_id"]
            cluster_overrides.setdefault(cid, {})[entry["variable"]] = entry["reason"]

        candidates = sorted(iv_map.keys(), key=lambda v: iv_map[v], reverse=True)
        selected: list[dict] = []
        rejected: list[dict] = []
        seen_clusters: set[str] = set()
        cluster_decisions: list[dict] = []

        # Apply manual_excludes first
        for var in candidates:
            if var in manual_excludes:
                rejected.append({"variable": var, "reason": manual_excludes[var]})

        # Apply cluster representative rule
        if cluster_rule != "none" and clusters:
            for cl in clusters:
                cid = cl["cluster_id"]
                vars_in_cluster = cluster_vars.get(cid, [])
                eligible = [v for v in vars_in_cluster if v not in manual_excludes]
                if not eligible:
                    continue

                # Check for manual override for this cluster
                overridden = False
                if cid in cluster_overrides:
                    for override_var, override_reason in cluster_overrides[cid].items():
                        if override_var in eligible:
                            if override_var not in seen_clusters:
                                selected.append({
                                    "variable": override_var,
                                    "reason": f"Cluster representative override: {override_reason}",
                                })
                                seen_clusters.add(cid)
                                cluster_decisions.append({
                                    "cluster_id": cid,
                                    "selected_variable": override_var,
                                    "reason": override_reason,
                                    "candidate_variables": eligible,
                                })
                                overridden = True
                            break

                if overridden:
                    continue

                # Pick representative by rule
                if cluster_rule == "highest_iv":
                    rep = eligible[0]  # Already sorted by IV descending
                    rep_reason = f"highest IV ({iv_map.get(rep, 0.0):.4f}) in cluster"
                elif cluster_rule == "lowest_missing":
                    rep = min(eligible, key=lambda v: 0.0)
                    rep_reason = "lowest missing rate in cluster"
                else:
                    continue

                if rep not in seen_clusters:
                    selected.append({"variable": rep, "reason": rep_reason})
                    seen_clusters.add(cid)
                    cluster_decisions.append({
                        "cluster_id": cid,
                        "selected_variable": rep,
                        "reason": rep_reason,
                        "candidate_variables": eligible,
                    })

            # Now process remaining variables not in any cluster (singletons / unclustered)
            for var in candidates:
                if var in manual_excludes:
                    continue
                if var in manual_includes:
                    if var not in [s["variable"] for s in selected]:
                        selected.append({"variable": var, "reason": manual_includes[var]})
                    continue
                cid = cluster_map.get(var)
                if cid and cid in seen_clusters:
                    continue
                if var in [s["variable"] for s in selected]:
                    continue
                if var in [r["variable"] for r in rejected]:
                    continue

                iv_info_val = iv_map.get(var, 0.0)
                if iv_info_val < min_iv:
                    rejected.append({"variable": var, "reason": f"IV {iv_info_val:.4f} below threshold {min_iv}"})
                    continue

                if len(selected) >= max_variables:
                    rejected.append({"variable": var, "reason": f"Reached max_variables limit ({max_variables})"})
                    continue

                selected.append({"variable": var, "reason": "IV above threshold"})
                if cid and cid not in seen_clusters:
                    seen_clusters.add(cid)
        else:
            # Original behaviour (no cluster representative rule)
            for var in candidates:
                if var in manual_excludes:
                    continue
                if var in manual_includes:
                    reason = manual_includes.get(var, "Manual inclusion")
                    if var not in [s["variable"] for s in selected]:
                        selected.append({"variable": var, "reason": reason})
                    seen_clusters.add(cluster_map.get(var, var))
                    continue

                iv_info_val = iv_map.get(var, 0.0)
                if iv_info_val < min_iv:
                    rejected.append({"variable": var, "reason": f"IV {iv_info_val:.4f} below threshold {min_iv}"})
                    continue

                cluster_id = cluster_map.get(var, var)
                if cluster_id in seen_clusters:
                    rejected.append({
                        "variable": var,
                        "reason": f"Lower IV than selected correlated variable in cluster {cluster_id}",
                    })
                    continue

                if len(selected) >= max_variables:
                    rejected.append({"variable": var, "reason": f"Reached max_variables limit ({max_variables})"})
                    continue

                selected.append({
                    "variable": var,
                    "reason": "IV above threshold and strongest in cluster" if cluster_id not in seen_clusters else "IV above threshold",
                })
                seen_clusters.add(cluster_id)

        # Trim to max_variables if needed (only when cluster_rule is active)
        if cluster_rule != "none" and len(selected) > max_variables:
            extra_vars = selected[max_variables:]
            selected = selected[:max_variables]
            for ev in extra_vars:
                rejected.append({"variable": ev["variable"], "reason": f"Reached max_variables limit ({max_variables})"})

        selection = {
            "schema_version": SCHEMA_SELECTION_DEFINITION,
            "min_iv": min_iv,
            "max_variables": max_variables,
            "cluster_representative_rule": cluster_rule if cluster_rule != "none" else None,
            "selected": selected,
            "rejected": rejected,
        }
        if cluster_decisions:
            selection["cluster_decisions"] = cluster_decisions

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"variable-selection-{context.step_spec.step_id}",
            payload=selection,
            metadata={
                "selected_count": len(selected),
                "rejected_count": len(rejected),
                "schema_version": SCHEMA_SELECTION_DEFINITION,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"selected_count": len(selected), "rejected_count": len(rejected)},
        )


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

                mask_expr = build_bin_condition(bin_def_entry, pl.col(variable), kind, bins, variable=variable, bin_id=bin_id)

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
