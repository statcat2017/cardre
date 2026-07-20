from __future__ import annotations

import logging
from typing import Any, cast

from polars.exceptions import ComputeError, SchemaError

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.artifacts import write_json_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes._training_utils import (
    prepare_supervised_training_data,
    resolve_supervised_feature_columns,
)
from cardre.nodes.contracts import NodeType
from cardre.nodes.selection._definition import merge_selection_definition

logger = logging.getLogger(__name__)


class FeatureSelectionFilterNode(NodeType):
    node_type = "cardre.feature_selection_filter"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition", "report"]
    output_roles: list[str] = ["definition"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        min_iv = params.get("min_iv", 0.0)
        try:
            if float(min_iv) < 0:
                errors.append("min_iv must be >= 0")
        except (ValueError, TypeError):
            errors.append("min_iv must be a number")

        max_missingness = params.get("max_missingness", 1.0)
        try:
            v = float(max_missingness)
            if v < 0 or v > 1:
                errors.append("max_missingness must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("max_missingness must be a number")

        max_correlation = params.get("max_correlation", 1.0)
        try:
            v = float(max_correlation)
            if v < 0 or v > 1:
                errors.append("max_correlation must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("max_correlation must be a number")

        min_variance = params.get("min_variance", 0.0)
        try:
            if float(min_variance) < 0:
                errors.append("min_variance must be >= 0")
        except (ValueError, TypeError):
            errors.append("min_variance must be a number")

        max_features = params.get("max_features")
        if max_features is not None:
            try:
                if int(max_features) < 1:
                    errors.append("max_features must be >= 1")
            except (ValueError, TypeError):
                errors.append("max_features must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        min_iv = float(params.get("min_iv", 0.02))
        max_missingness = float(params.get("max_missingness", 0.5))
        max_correlation = float(params.get("max_correlation", 0.85))
        min_variance = float(params.get("min_variance", 1e-6))
        max_features = params.get("max_features")

        prepared = prepare_supervised_training_data(
            context,
            operation="feature_selection_filter",
        )
        df = prepared.frame
        train_art = context.require_train_artifact("feature_selection_filter")
        numeric_cols = resolve_supervised_feature_columns(
            df,
            target_column=prepared.target_column,
            params=params,
        )

        iv_map: dict[str, float] = {}
        reader = ArtifactEvidenceReader(store)
        iv_lf = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        if iv_lf is not None:
            iv_df = iv_lf.dataframe.collect()
            for row in iv_df.iter_rows():
                var_name = str(row[0])
                iv_val = float(row[1])
                iv_map[var_name] = iv_val

        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        n_rows = df.height
        null_counts = {c: int(df[c].null_count()) for c in numeric_cols}
        for col in list(numeric_cols):
            missingness = null_counts[col] / n_rows if n_rows > 0 else 0
            if missingness > max_missingness:
                rejected.append({
                    "variable": col,
                    "reason": f"Missingness {missingness:.2%} exceeds threshold {max_missingness:.2%}",
                    "method": "missingness",
                    "score": round(missingness, 6),
                })
                numeric_cols.remove(col)

        variances = {c: float(cast(Any, df[c].var())) for c in numeric_cols}
        for col in list(numeric_cols):
            try:
                variance = variances[col]
                if variance < min_variance:
                    rejected.append({
                        "variable": col,
                        "reason": f"Variance {variance:.6f} below threshold {min_variance}",
                        "method": "variance",
                        "score": round(variance, 6),
                    })
                    numeric_cols.remove(col)
            except (TypeError, ValueError) as exc:
                logger.warning("Variance filter skipped for column %s: %s", col, exc)

        if iv_map:
            for col in list(numeric_cols):
                iv_val = iv_map.get(col, 0.0)
                if iv_val < min_iv:
                    rejected.append({
                        "variable": col,
                        "reason": f"IV {iv_val:.4f} below threshold {min_iv}",
                        "method": "iv",
                        "score": round(iv_val, 6),
                    })
                    numeric_cols.remove(col)

        if max_correlation < 1.0 and len(numeric_cols) > 1:
            try:
                corr_matrix = df.select(numeric_cols).corr()
                n_cols = len(numeric_cols)
                to_remove: set[str] = set()
                for i in range(n_cols):
                    if numeric_cols[i] in to_remove:
                        continue
                    for j in range(i + 1, n_cols):
                        if numeric_cols[j] in to_remove:
                            continue
                        corr_val = abs(float(corr_matrix[i, j]))
                        if corr_val > max_correlation:
                            vi = iv_map.get(numeric_cols[i], 0.0)
                            vj = iv_map.get(numeric_cols[j], 0.0)
                            if vi >= vj:
                                to_remove.add(numeric_cols[j])
                            else:
                                to_remove.add(numeric_cols[i])
                                break

                for col in to_remove:
                    if col in numeric_cols:
                        rejected.append({
                            "variable": col,
                            "reason": f"Correlation exceeds threshold {max_correlation}",
                            "method": "correlation",
                            "score": 1.0,
                        })
                        numeric_cols.remove(col)
            except (ComputeError, SchemaError, ValueError, TypeError) as exc:
                logger.warning("Correlation filter skipped: %s", exc)

        for col in numeric_cols:
            iv_value: float | None = iv_map.get(col)
            selected.append({
                "variable": col,
                "reason": "Passed all filter thresholds",
                "method": "filter",
                "iv": round(iv_value, 6) if iv_value is not None else None,
            })

        if max_features and len(selected) > max_features:
            selected.sort(key=lambda x: x.get("iv") or 0.0, reverse=True)
            overflow = selected[max_features:]
            selected = selected[:max_features]
            for entry in overflow:
                rejected.append({
                    "variable": entry["variable"],
                    "reason": f"Exceeds max_features={max_features}",
                    "method": "max_features",
                    "score": entry.get("iv") or 0.0,
                })

        selection = {
            "method": "filter",
            "params": {
                "min_iv": min_iv,
                "max_missingness": max_missingness,
                "max_correlation": max_correlation,
                "min_variance": min_variance,
                "max_features": max_features,
            },
            "selected": selected,
            "rejected": rejected,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "source_artifact_id": train_art.artifact_id,
        }

        def_art = next((a for a in context.input_artifacts if a.role == "definition"), None)
        if def_art:
            try:
                selection = merge_selection_definition(
                    reader, def_art.artifact_id,
                    key="selection_filter", selection=selection,
                )
            except (KeyError, TypeError, AttributeError):
                logger.warning("Could not merge existing selection definition", exc_info=True)

        art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"feature-selection-filter-{context.step_spec.step_id}",
            payload=selection,
            metadata={"method": "filter", "selected_count": len(selected)},
        )
        return NodeOutput(
            artifacts=[art],
            metrics={"selected_count": len(selected), "rejected_count": len(rejected)})
