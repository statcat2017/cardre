from __future__ import annotations

from typing import Any, cast

import numpy as np
import polars as pl

from cardre._evidence.kinds import EvidenceKind, EvidenceNotFoundError
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import SCHEMA_VARIABLE_CLUSTERING_EVIDENCE
from cardre.artifacts import write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.nodes._bin_mask import build_bin_condition
from cardre.nodes.contracts import NodeType


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
            default_method="correlation_threshold",
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
                        ParameterDefinition(
                            name="minimum_pair_count", label="Minimum Pair Count",
                            kind="integer", default=30,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Minimum number of joint non-null rows required for a reliable pairwise correlation estimate",
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
                        ParameterDefinition(
                            name="minimum_pair_count", label="Minimum Pair Count",
                            kind="integer", default=30,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Minimum number of joint non-null rows required for a reliable pairwise correlation estimate",
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

        valid_methods = {"correlation_threshold", "hierarchical", "varclus_pca", "mixed_type", "target_aware"}
        if method not in valid_methods:
            errors.append(f"Unknown method: {method!r}")
            return errors

        if method in ("varclus_pca", "mixed_type", "target_aware"):
            errors.append(f"Method {method!r} is not yet available")
            return errors

        candidate_limit = params.get("candidate_limit", 50)
        try:
            if int(candidate_limit) < 1:
                errors.append("candidate_limit must be >= 1")
        except (ValueError, TypeError):
            errors.append("candidate_limit must be an integer")

        similarity_metric = params.get("similarity_metric", "pearson")
        if similarity_metric not in ("pearson", "spearman"):
            errors.append(f"Unknown similarity_metric: {similarity_metric!r}")
        if similarity_metric == "spearman":
            try:
                import scipy.stats  # noqa: F401
            except ImportError:
                errors.append("spearman requires scipy, which is a core dependency of cardre")

        if method == "correlation_threshold":
            threshold = params.get("threshold", params.get("correlation_threshold", 0.7))
            try:
                if not (0 < float(threshold) < 1):
                    errors.append("threshold must be between 0 and 1 (exclusive)")
            except (ValueError, TypeError):
                errors.append("threshold must be a number")

        elif method == "hierarchical":
            cut_threshold = params.get("cut_threshold", 0.3)
            try:
                if float(cut_threshold) <= 0:
                    errors.append("cut_threshold must be > 0")
            except (ValueError, TypeError):
                errors.append("cut_threshold must be a number")

            linkage = params.get("linkage", "average")
            if linkage not in ("average", "complete"):
                errors.append(f"Unknown linkage: {linkage!r}")

        input_representation = params.get("input_representation", "raw_train")
        if input_representation not in ("raw_train", "woe_train"):
            errors.append(f"Unknown input_representation: {input_representation!r}")

        missing_handling = params.get("missing_handling", "pairwise")
        if missing_handling not in ("pairwise", "complete_case"):
            errors.append(f"Unknown missing_handling: {missing_handling!r}")

        representative_rule = params.get("representative_rule", "highest_iv")
        if representative_rule not in ("highest_iv", "lowest_missing", "manual"):
            errors.append(f"Unknown representative_rule: {representative_rule!r}")

        minimum_pair_count = params.get("minimum_pair_count", 30)
        try:
            if int(minimum_pair_count) < 1:
                errors.append("minimum_pair_count must be >= 1")
        except (ValueError, TypeError):
            errors.append("minimum_pair_count must be a positive integer")

        return errors

    def _build_woe_columns(
        self, df: pl.DataFrame, bin_def: Any, woe_table: Any,
    ) -> list[pl.Expr]:
        woe_exprs: list[pl.Expr] = []
        for var_def in bin_def.variables:
            variable = var_def.variable
            kind = var_def.kind
            bins = var_def.bins

            if variable not in df.columns:
                continue

            woe_expr: Any = None
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

    @staticmethod
    def _tie_aware_rank(values: np.ndarray) -> np.ndarray:
        """Assign average ranks, handling ties correctly."""
        from scipy.stats import rankdata

        return cast(np.ndarray[Any, Any], rankdata(values, method="average").astype(float))

    def _compute_correlation_matrix(
        self, df: pl.DataFrame, columns: list[str],
        method: str, missing_handling: str,
        absolute: bool, minimum_pair_count: int = 30,
    ) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
        import numpy as np

        warnings_list: list[dict[str, Any]] = []
        n = len(columns)
        arr = np.eye(n)

        if n < 2:
            df_corr = pl.DataFrame(arr, schema=columns, orient="row").with_row_index("_col")
            return df_corr, warnings_list

        if missing_handling == "complete_case":
            matrix_df = df.select(columns).drop_nulls()
            mat = matrix_df.to_numpy()
            if mat.shape[0] == 0:
                warnings_list.append({
                    "code": "NO_COMPLETE_CASE_ROWS",
                    "severity": "warning",
                    "variable_a": "",
                    "variable_b": "",
                    "message": "No complete-case rows available; returning identity correlation matrix",
                })
                df_corr = pl.DataFrame(arr, schema=columns, orient="row").with_row_index("_col")
                return df_corr, warnings_list
            if mat.shape[0] < minimum_pair_count:
                warnings_list.append({
                    "code": "LOW_PAIR_COUNT",
                    "severity": "warning",
                    "variable_a": "",
                    "variable_b": "",
                    "message": f"Complete-case rows ({mat.shape[0]}) below minimum pair count ({minimum_pair_count})",
                })
            if method == "spearman":
                ranks = np.apply_along_axis(self._tie_aware_rank, 0, mat)
                corr_mat = np.corrcoef(ranks.T)
            else:
                corr_mat = np.corrcoef(mat.T)
            corr_mat = np.nan_to_num(corr_mat, nan=0.0)
            arr = corr_mat
        else:
            mat = df.select(columns).to_numpy()
            for i in range(n):
                for j in range(i + 1, n):
                    col_i = mat[:, i]
                    col_j = mat[:, j]
                    valid = ~(np.isnan(col_i) | np.isnan(col_j))
                    n_valid = int(valid.sum())
                    if n_valid == 0:
                        warnings_list.append({
                            "code": "NO_PAIRWISE_OVERLAP",
                            "severity": "warning",
                            "variable_a": columns[i],
                            "variable_b": columns[j],
                            "message": (
                                f"No joint non-null rows for {columns[i]!r} vs {columns[j]!r}; "
                                f"correlation set to 0.0"
                            ),
                        })
                        arr[i, j] = 0.0
                        arr[j, i] = 0.0
                        continue
                    if n_valid < minimum_pair_count:
                        warnings_list.append({
                            "code": "LOW_PAIR_COUNT",
                            "severity": "warning",
                            "variable_a": columns[i],
                            "variable_b": columns[j],
                            "message": (
                                f"Pairwise correlation {columns[i]!r} vs {columns[j]!r}: "
                                f"only {n_valid} joint non-null rows (< {minimum_pair_count}); "
                                f"correlation estimate may be unreliable"
                            ),
                        })
                    xi = col_i[valid]
                    xj = col_j[valid]
                    if method == "spearman":
                        xi = self._tie_aware_rank(xi)
                        xj = self._tie_aware_rank(xj)
                    corr_val = np.corrcoef(xi, xj)[0, 1]
                    corr_val = 0.0 if np.isnan(corr_val) else corr_val
                    arr[i, j] = corr_val
                    arr[j, i] = corr_val

        if absolute:
            arr = np.abs(arr)

        return pl.DataFrame(arr, schema=columns, orient="row").with_row_index("_col"), warnings_list

    def _correlation_threshold_clusters(
        self, columns: list[str],
        corr_matrix: pl.DataFrame, threshold: float,
        iv_map: dict[str, float], missing_map: dict[str, float],
        representative_rule: str,
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:

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

        clusters_out: list[dict[str, Any]] = []
        singletons: list[str] = []
        warnings_list: list[dict[str, Any]] = []

        for cid, members in enumerate(cluster_list, 1):
            var_names = [columns[m] for m in members]
            if len(var_names) == 1:
                singletons.append(var_names[0])
                continue

            max_corr = 0.0
            for i in members:
                for j in members:
                    if i < j:
                        corr_val = float(arr[i, j])
                        if corr_val > max_corr:
                            max_corr = corr_val

            rep = self._pick_representative(
                var_names, iv_map, missing_map, representative_rule,
            )

            enriched_members: list[dict[str, Any]] = []
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
        self, columns: list[str],
        corr_matrix: pl.DataFrame, linkage: str, cut_threshold: float,
        iv_map: dict[str, float], missing_map: dict[str, float],
        representative_rule: str,
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        import numpy as np

        arr = 1.0 - corr_matrix.drop("_col").to_numpy()
        n = len(columns)
        np.fill_diagonal(arr, 0.0)

        clusters: list[list[int]] = [[i] for i in range(n)]

        def cluster_distance(c1: list[int], c2: list[int]) -> float:
            if linkage == "complete":
                return float(max(arr[i, j] for i in c1 for j in c2))
            return float(sum(arr[i, j] for i in c1 for j in c2) / (len(c1) * len(c2)))

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

        clusters_out: list[dict[str, Any]] = []
        singletons: list[str] = []
        warnings_list: list[dict[str, Any]] = []

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

        best = max(variables, key=lambda v: iv_map.get(v, 0.0))
        return {"variable": best, "reason": "highest IV"}

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params

        method = str(params.get("method", "correlation_threshold"))
        similarity_metric = str(params.get("similarity_metric", "pearson"))
        absolute_correlation = bool(params.get("absolute_correlation", True))
        candidate_limit = int(params.get("candidate_limit", 50))
        missing_handling = str(params.get("missing_handling", "pairwise"))
        representative_rule = str(params.get("representative_rule", "highest_iv"))
        minimum_pair_count = int(params.get("minimum_pair_count", 30))

        if method == "correlation_threshold":
            threshold = float(cast(Any, params.get("threshold", params.get("correlation_threshold", 0.7))))
        elif method == "hierarchical":
            threshold = float(cast(Any, params.get("cut_threshold", 0.3)))
            linkage = str(params.get("linkage", "average"))
        else:
            raise ValueError(f"Unknown or unavailable clustering method: {method!r}")

        input_representation = params.get("input_representation", "raw_train")

        train_artifact = context.require_train_artifact("VariableClusteringNode")
        df = reader.read_dataframe(train_artifact)

        iv_map = self._load_iv_map(reader, context)
        missing_map = {col: df[col].null_count() / df.height for col in df.columns if df.height > 0}

        bin_def, woe_table = self._load_binning_artifacts(reader, context, input_representation)

        candidates = self._select_candidates(df, bin_def, woe_table, iv_map, input_representation, candidate_limit)

        clusters_out, singleton_variables, warnings_list = self._cluster_candidates(
            df, candidates, bin_def, woe_table, iv_map, missing_map,
            input_representation, method, similarity_metric, missing_handling,
            absolute_correlation, minimum_pair_count, linkage if method == "hierarchical" else None,
            threshold, representative_rule, candidate_limit,
        )

        clustering_report = {
            "schema_version": SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
            "method": method,
            "input_representation": input_representation,
            "similarity_metric": similarity_metric,
            "absolute_correlation": absolute_correlation,
            "threshold": threshold,
            "missing_handling": missing_handling,
            "candidate_limit": candidate_limit,
            "minimum_pair_count": minimum_pair_count,
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
                "minimum_pair_count": minimum_pair_count,
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

    def _load_iv_map(self, reader: ArtifactEvidenceReader, context: ExecutionContext) -> dict[str, float]:
        iv_map: dict[str, float] = {}
        try:
            iv_table = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        except (KeyError, TypeError):
            iv_table = None
        if iv_table is not None:
            try:
                iv_df = iv_table.dataframe.collect()
                for row in iv_df.iter_rows():
                    iv_map[str(row[0])] = float(row[1])
            except (KeyError, TypeError):
                iv_map = {}
        return iv_map

    def _load_binning_artifacts(
        self, reader: ArtifactEvidenceReader, context: ExecutionContext, input_representation: str,
    ) -> tuple[Any, Any]:
        if input_representation != "woe_train":
            return None, None
        try:
            bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
            woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)
        except (KeyError, TypeError, EvidenceNotFoundError):
            bin_def = None
            woe_table = None
        return bin_def, woe_table

    def _select_candidates(
        self, df: pl.DataFrame, bin_def: Any, woe_table: Any,
        iv_map: dict[str, float], input_representation: str, candidate_limit: int,
    ) -> list[str]:
        if input_representation == "woe_train" and bin_def is not None and woe_table is not None:
            candidates: list[str] = []
            for var_def in bin_def.variables:
                vname = var_def.variable
                if vname not in df.columns:
                    continue
                has_woe = any(
                    woe_table.mapping.get(vname, {}).get(b["bin_id"]) is not None
                    for b in var_def.bins
                )
                if has_woe:
                    candidates.append(vname)
            if iv_map:
                candidates = sorted(candidates, key=lambda c: iv_map.get(c, 0.0), reverse=True)
            if not candidates:
                candidates = [c for c in df.columns if df.schema[c].is_numeric()]
        else:
            numeric_cols = [c for c in df.columns if df.schema[c].is_numeric()]
            if iv_map:
                candidates = [c for c in numeric_cols if c in iv_map]
                candidates = sorted(candidates, key=lambda c: iv_map.get(c, 0.0), reverse=True)
            else:
                candidates = numeric_cols
        return candidates[:candidate_limit]

    def _cluster_candidates(
        self, df: pl.DataFrame, candidates: list[str], bin_def: Any, woe_table: Any,
        iv_map: dict[str, float], missing_map: dict[str, float],
        input_representation: str, method: str, similarity_metric: str,
        missing_handling: str, absolute_correlation: bool, minimum_pair_count: int,
        linkage: str | None, threshold: float, representative_rule: str, candidate_limit: int,
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        clusters_out: list[dict[str, Any]] = []
        singleton_variables: list[str] = []
        warnings_list: list[dict[str, Any]] = []

        if len(candidates) < 2:
            for col in candidates:
                singleton_variables.append(col)
            if candidates:
                warnings_list.append({
                    "code": "INSUFFICIENT_CANDIDATES",
                    "severity": "warning",
                    "variable_a": "",
                    "variable_b": "",
                    "message": f"Only {len(candidates)} numeric candidate(s); clustering is pass-through",
                })
            return clusters_out, singleton_variables, warnings_list

        try:
            if input_representation == "woe_train":
                if bin_def is None or woe_table is None:
                    for col in candidates:
                        singleton_variables.append(col)
                    warnings_list.append({
                        "code": "WOE_EVIDENCE_MISSING",
                        "severity": "warning",
                        "variable_a": "",
                        "variable_b": "",
                        "message": "WOE train representation requested but bin definition or WOE table not found; using singleton pass-through on raw variables",
                    })
                    return clusters_out, singleton_variables, warnings_list
                woe_exprs = self._build_woe_columns(df, bin_def, woe_table)
                if woe_exprs:
                    woe_df = df.with_columns(woe_exprs)
                    woe_cols = [str(e.meta.output_name) for e in woe_exprs]
                    woe_cols = [c for c in woe_cols if c.replace("_woe", "") in candidates]
                    woe_cols = woe_cols[:candidate_limit]
                    if len(woe_cols) < 2:
                        for col in candidates:
                            singleton_variables.append(col)
                        warnings_list.append({
                            "code": "INSUFFICIENT_WOE_COLUMNS",
                            "severity": "warning",
                            "variable_a": "",
                            "variable_b": "",
                            "message": "Fewer than 2 WOE-transformed columns available; using singleton pass-through",
                        })
                    else:
                        corr_matrix, corr_warnings = self._compute_correlation_matrix(
                            woe_df, woe_cols, similarity_metric, missing_handling, absolute_correlation,
                            minimum_pair_count=minimum_pair_count,
                        )
                        warnings_list.extend(corr_warnings)
                        woe_candidate_map: dict[str, str] = {c: c.replace("_woe", "") for c in woe_cols}
                        iv_map_woe: dict[str, float] = {wc: iv_map.get(oc, 0.0) for wc, oc in woe_candidate_map.items()}
                        missing_map_woe: dict[str, float] = {wc: missing_map.get(oc, 0.0) for wc, oc in woe_candidate_map.items()}

                        if method == "hierarchical":
                            clusters_out, singleton_variables, cluster_warnings = self._hierarchical_clusters(
                                woe_cols, corr_matrix, cast(str, linkage), threshold,
                                iv_map_woe, missing_map_woe, representative_rule,
                            )
                        else:
                            clusters_out, singleton_variables, cluster_warnings = self._correlation_threshold_clusters(
                                woe_cols, corr_matrix, threshold,
                                iv_map_woe, missing_map_woe, representative_rule,
                            )
                        warnings_list.extend(cluster_warnings)

                        for cl in clusters_out:
                            mapped_vars: list[dict[str, Any]] = []
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
                        "code": "NO_WOE_COLUMNS",
                        "severity": "warning",
                        "variable_a": "",
                        "variable_b": "",
                        "message": "No WOE-transformed columns could be built; using singleton pass-through on raw variables",
                    })
            else:
                corr_matrix, corr_warnings = self._compute_correlation_matrix(
                    df, candidates, similarity_metric, missing_handling, absolute_correlation,
                    minimum_pair_count=minimum_pair_count,
                )
                warnings_list.extend(corr_warnings)

                if method == "hierarchical":
                    clusters_out, singleton_variables, cluster_warnings = self._hierarchical_clusters(
                        candidates, corr_matrix, cast(str, linkage), threshold,
                        iv_map, missing_map, representative_rule,
                    )
                else:
                    clusters_out, singleton_variables, cluster_warnings = self._correlation_threshold_clusters(
                        candidates, corr_matrix, threshold,
                        iv_map, missing_map, representative_rule,
                    )
                warnings_list.extend(cluster_warnings)

        except ValueError:
            for col in candidates:
                singleton_variables.append(col)
            warnings_list.append({
                "code": "CLUSTERING_FAILED",
                "severity": "warning",
                "variable_a": "",
                "variable_b": "",
                "message": "Clustering computation failed; using singleton pass-through",
            })

        return clusters_out, singleton_variables, warnings_list
