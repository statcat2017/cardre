from __future__ import annotations

from typing import Any

import polars as pl

from cardre._evidence.schemas import SCHEMA_PROFILE_SUMMARY
from cardre.artifacts import write_json_artifact
from cardre.domain.diagnostics import JsonDict
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterDefinition,
)
from cardre.nodes._dataset_quality import quality_warnings as _quality_warnings
from cardre.nodes.contracts import NodeType


class ProfileDatasetNode(NodeType):
    node_type = "cardre.profile_dataset"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "test", "oot"]
    output_roles: list[str] = ["report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Profile Dataset",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="profile_max_rows",
                            label="Profile Max Rows",
                            kind="integer",
                            help_text="Maximum rows to read for profiling (None = all rows). "
                                      "Reduces memory for large datasets; statistics will be based on a sample.",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        profile_max_rows = params.get("profile_max_rows")
        if profile_max_rows is not None:
            if isinstance(profile_max_rows, bool) or not isinstance(profile_max_rows, int) or profile_max_rows < 1:
                errors.append(f"profile_max_rows must be a positive integer, got {profile_max_rows!r}")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        input_artifact = context.input_artifacts[0]
        params = context.validated_params
        profile_max_rows: int | None = params.get("profile_max_rows")

        df = pl.read_parquet(store.artifact_path(input_artifact), n_rows=profile_max_rows)  # cardre-allow-artifact-read: dataset-frame-input

        quality_warnings: list[JsonDict] = []
        recommended_exclude: list[str] = []

        quality_warnings, recommended_exclude = _quality_warnings(df)

        node_warnings: list[JsonDict] = []
        metadata: dict[str, Any] = {"source_artifact_id": input_artifact.artifact_id}

        if profile_max_rows is not None:
            metadata["profile_sampled"] = True
            metadata["profile_max_rows"] = profile_max_rows
            node_warnings.append({
                "code": "PROFILE_SAMPLED",
                "message": f"Profile based on first {profile_max_rows} rows; "
                           f"statistics may not represent the full dataset.",
            })

        report = {
            "row_count": df.height,
            "column_count": df.width,
            "columns": list(df.columns),
            "dtypes": {c: str(df.schema[c]) for c in df.columns},
            "null_counts": {c: int(df[c].null_count()) for c in df.columns},
            "numeric_stats": self._numeric_stats(df),
            "profile_steps": [],
            "quality_warnings": quality_warnings,
            "warnings": quality_warnings,
            "recommended_exclude_columns": recommended_exclude,
        }

        report["profiles"] = [{
            "row_count": report["row_count"],
            "column_count": report["column_count"],
            "columns": report["columns"],
            "dtypes": report["dtypes"],
            "null_counts": report["null_counts"],
            "numeric_stats": report["numeric_stats"],
        }]

        artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"profile-{context.step_spec.step_id}",
            payload=report,
            metadata={**metadata, "schema_version": SCHEMA_PROFILE_SUMMARY},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height},
            warnings=node_warnings or None,
        )

    def _numeric_stats(self, df: pl.DataFrame) -> dict[str, dict[str, float | None]]:
        numeric_cols = [c for c in df.columns if df.schema[c].is_numeric()]
        if not numeric_cols:
            return {}

        empty_cols = {c for c in numeric_cols if df[c].drop_nulls().is_empty()}
        available = [c for c in numeric_cols if c not in empty_cols]

        stats: dict[str, dict[str, float | None]] = {c: {"min": None, "max": None, "mean": None, "std": None} for c in numeric_cols}

        if available:
            aggs = df.select([
                pl.col(c).min().alias(f"{c}__min")
                for c in available
            ] + [
                pl.col(c).max().alias(f"{c}__max")
                for c in available
            ] + [
                pl.col(c).mean().alias(f"{c}__mean")
                for c in available
            ] + [
                pl.col(c).std().alias(f"{c}__std")
                for c in available
            ])
            row = aggs.row(0)
            half = len(available)
            for i, col in enumerate(available):
                stats[col] = {
                    "min": float(row[i]),
                    "max": float(row[i + half]),
                    "mean": float(row[i + half * 2]),
                    "std": float(row[i + half * 3]) if row[i + half * 3] is not None else None,
                }
        return stats
