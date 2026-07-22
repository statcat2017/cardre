from __future__ import annotations

from typing import Any

import polars as pl

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_EXCLUSION_SUMMARY
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


class ApplyExclusionsNode(NodeType):
    node_type = "cardre.apply_exclusions"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "definition"]
    output_roles: list[str] = ["input", "train"]

    __definition__ = NodeDefinition(
        node_type="cardre.apply_exclusions",
        version="1",
        category="transform",
        description="Apply exclusion rules to filter rows",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=("dataset",)), ArtifactRoleSpec("train", required=False, kinds=("dataset",)), ArtifactRoleSpec("definition", required=False, kinds=("definition",)))),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=("dataset",)), ArtifactRoleSpec("train", required=False, kinds=("dataset",)))),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        dataset_artifact = context.inputs.first("input") or context.inputs.first("train")
        rules = params.get("rules", [])

        df = context.inputs.read_dataframe(dataset_artifact)
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

        context.outputs.publish_table(
            role=getattr(dataset_artifact, "role", "input"),
            kind=EvidenceKind.MODELLING_METADATA,
            frame=df,
            metadata={
                "source_artifact_id": getattr(dataset_artifact, "artifact_id", ""),
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
        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.EXCLUSION_SUMMARY,
            payload=exclusion_report,
            metadata={"source_artifact_id": getattr(dataset_artifact, "artifact_id", ""), "schema_version": SCHEMA_EXCLUSION_SUMMARY},
        )

        context.outputs.add_metric("rows_before", n_before)
        context.outputs.add_metric("rows_after", df.height)
        return context.outputs.build_result()


class ExplicitMissingOutlierTreatmentNode(NodeType):
    node_type = "cardre.explicit_missing_outlier_treatment"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot"]
    output_roles: list[str] = ["train", "test", "oot"]

    __definition__ = NodeDefinition(
        node_type="cardre.explicit_missing_outlier_treatment",
        version="1",
        category="apply",
        description="Apply explicit missing value imputation and outlier capping/floating",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("train", required=True, kinds=("dataset",)), ArtifactRoleSpec("test", required=False, kinds=("dataset",)), ArtifactRoleSpec("oot", required=False, kinds=("dataset",)))),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("train", required=True, kinds=("dataset",)), ArtifactRoleSpec("test", required=False, kinds=("dataset",)), ArtifactRoleSpec("oot", required=False, kinds=("dataset",)))),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        imputations = params.get("imputations", {})
        caps = params.get("caps", {})
        floors = params.get("floors", {})

        treatment_report: dict[str, Any] = {"imputations": {}, "caps": {}, "floors": {}}

        all_roles = []
        for role in ("train", "test", "oot"):
            all_roles.extend(context.inputs.by_role(role))
        data_inputs = all_roles
        for input_art in data_inputs:
            df = context.inputs.read_dataframe(input_art)
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

            context.outputs.publish_table(
                role=getattr(input_art, "role", "train"),
                kind=EvidenceKind.MODELLING_METADATA,
                frame=df,
                metadata={
                    "source_artifact_id": getattr(input_art, "artifact_id", ""),
                    "treatment": {k: list(v.keys()) for k, v in affected.items() if v},
                },
            )
            treatment_report["imputations"].update(affected["imputations"])
            treatment_report["caps"].update(affected["caps"])
            treatment_report["floors"].update(affected["floors"])

        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.EXCLUSION_SUMMARY,
            payload=treatment_report,
            metadata={},
        )

        context.outputs.add_metric("output_count", len(data_inputs))
        return context.outputs.build_result()
