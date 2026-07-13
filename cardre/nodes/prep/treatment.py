from __future__ import annotations

from typing import Any

import polars as pl

from cardre._evidence.schemas import SCHEMA_EXCLUSION_SUMMARY
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType


class ApplyExclusionsNode(NodeType):
    node_type = "cardre.apply_exclusions"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "definition"]
    output_roles: list[str] = ["input", "train"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params
        dataset_artifact = next(a for a in context.input_artifacts if a.role in ("input", "train"))
        rules = params.get("rules", [])

        df = pl.read_parquet(store.artifact_path(dataset_artifact))
        n_before = df.height

        rule_counts = []
        for rule in rules:
            column = rule.get("column", "")
            operator = rule.get("operator", "")
            value = rule.get("value")
            reason = rule.get("reason", "")

            if not reason:
                raise ValueError(f"Exclusion rule for column '{column}' requires a non-empty reason")
            if column not in df.columns:
                raise ValueError(f"Exclusion rule references unknown column '{column}'")
            if operator not in ("==", "!=", "<", "<=", ">", ">=", "in", "not_in", "is_null", "is_not_null"):
                raise ValueError(f"Unsupported exclusion operator '{operator}'")

            col_expr = pl.col(column)
            if df.schema[column] == pl.Utf8 and isinstance(value, (int, float)):
                col_expr = pl.col(column).cast(pl.Float64)

            if operator == "==":
                exclusion_mask = col_expr == value
            elif operator == "!=":
                exclusion_mask = col_expr != value
            elif operator == "<":
                exclusion_mask = col_expr < value
            elif operator == "<=":
                exclusion_mask = col_expr <= value
            elif operator == ">":
                exclusion_mask = col_expr > value
            elif operator == ">=":
                exclusion_mask = col_expr >= value
            elif operator == "in":
                if not isinstance(value, (list, tuple, set)):
                    raise ValueError(f"Exclusion operator 'in' for column '{column}' requires a list-like value")
                exclusion_mask = col_expr.is_in(list(value))
            elif operator == "not_in":
                if not isinstance(value, (list, tuple, set)):
                    raise ValueError(f"Exclusion operator 'not_in' for column '{column}' requires a list-like value")
                exclusion_mask = ~col_expr.is_in(list(value))
            elif operator == "is_null":
                exclusion_mask = col_expr.is_null()
            elif operator == "is_not_null":
                exclusion_mask = col_expr.is_not_null()
            removed = int(df.select(exclusion_mask.sum()).item())
            df = df.filter(~exclusion_mask)
            rule_counts.append({
                "column": column,
                "operator": operator,
                "value": value,
                "reason": reason,
                "rows_removed": removed,
            })

        dataset_artifact = write_parquet_artifact(
            store, artifact_type="dataset",
            role=dataset_artifact.role,
            stem=f"excluded-{context.step_spec.step_id}",
            frame=df,
            metadata={
                "source_artifact_id": dataset_artifact.artifact_id,
                "rows_before": n_before,
                "rows_after": df.height,
            },
        )

        exclusion_report = {
            "rows_before": n_before,
            "rows_after": df.height,
            "rows_excluded": n_before - df.height,
            "rules": rule_counts,
        }
        exclusion_report_artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"exclusion-report-{context.step_spec.step_id}",
            payload=exclusion_report,
            metadata={"source_artifact_id": dataset_artifact.artifact_id, "schema_version": SCHEMA_EXCLUSION_SUMMARY},
        )

        return NodeOutput(
            artifacts=[dataset_artifact, exclusion_report_artifact],
            metrics={"rows_before": n_before, "rows_after": df.height})


class ExplicitMissingOutlierTreatmentNode(NodeType):
    node_type = "cardre.explicit_missing_outlier_treatment"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot"]
    output_roles: list[str] = ["train", "test", "oot"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params
        imputations = params.get("imputations", {})
        caps = params.get("caps", {})
        floors = params.get("floors", {})

        treatment_report: dict[str, Any] = {"imputations": {}, "caps": {}, "floors": {}}

        output_artifacts = []
        data_inputs = [
            input_art
            for input_art in context.input_artifacts
            if input_art.role in ("train", "test", "oot")
        ]
        for input_art in data_inputs:
            df = pl.read_parquet(store.artifact_path(input_art))
            affected: dict[str, dict[str, Any]] = {"imputations": {}, "caps": {}, "floors": {}}

            for col_name, config in imputations.items():
                if col_name not in df.columns:
                    raise ValueError(f"Imputation target column '{col_name}' not found")
                reason = config.get("reason", "")
                if not reason:
                    raise ValueError(f"Imputation for '{col_name}' requires a reason")
                val = config.get("value")
                null_count = int(df[col_name].null_count())
                df = df.with_columns(pl.col(col_name).fill_null(val))
                affected["imputations"][col_name] = {"filled_nulls": null_count, "value": val, "reason": reason}

            for col_name, config in caps.items():
                if col_name not in df.columns:
                    raise ValueError(f"Cap target column '{col_name}' not found")
                reason = config.get("reason", "")
                if not reason:
                    raise ValueError(f"Cap for '{col_name}' requires a reason")
                val = config.get("value")
                if not df.schema[col_name].is_numeric():
                    raise ValueError(f"Cap column '{col_name}' must be numeric")
                capped_count = int(df.filter(pl.col(col_name) > val).height)
                df = df.with_columns(pl.when(pl.col(col_name) > val).then(val).otherwise(pl.col(col_name)).alias(col_name))
                affected["caps"][col_name] = {"capped_count": capped_count, "value": val, "reason": reason}

            for col_name, config in floors.items():
                if col_name not in df.columns:
                    raise ValueError(f"Floor target column '{col_name}' not found")
                reason = config.get("reason", "")
                if not reason:
                    raise ValueError(f"Floor for '{col_name}' requires a reason")
                val = config.get("value")
                if not df.schema[col_name].is_numeric():
                    raise ValueError(f"Floor column '{col_name}' must be numeric")
                floored_count = int(df.filter(pl.col(col_name) < val).height)
                df = df.with_columns(pl.when(pl.col(col_name) < val).then(val).otherwise(pl.col(col_name)).alias(col_name))
                affected["floors"][col_name] = {"floored_count": floored_count, "value": val, "reason": reason}

            output_art = write_parquet_artifact(
                store, artifact_type="dataset",
                role=input_art.role,
                stem=f"treated-{input_art.role}-{context.step_spec.step_id}",
                frame=df,
                metadata={
                    "source_artifact_id": input_art.artifact_id,
                    "treatment": {k: list(v.keys()) for k, v in affected.items() if v},
                },
            )
            output_artifacts.append(output_art)
            treatment_report["imputations"].update(affected["imputations"])
            treatment_report["caps"].update(affected["caps"])
            treatment_report["floors"].update(affected["floors"])

        treatment_report_artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"treatment-report-{context.step_spec.step_id}",
            payload=treatment_report,
            metadata={},
        )
        output_artifacts.append(treatment_report_artifact)

        return NodeOutput(
            artifacts=output_artifacts,
            metrics={"output_count": len(output_artifacts)})
