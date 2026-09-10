from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)
from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterDefinition,
)


class ImportTabularDatasetNode(NodeType):
    node_type = "cardre.import_dataset"
    version = "1"
    category = "transform"

    __definition__ = NodeDefinition(
        node_type="cardre.import_dataset",
        version="1",
        category="transform",
        description="Import tabular dataset from a Parquet file",
        input_contract=ArtifactContract(),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=(EvidenceKind.MODELLING_METADATA,), media_types=("application/vnd.apache.parquet",), schema_versions=()),)),
    )

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Import Tabular Dataset",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="source_path",
                            label="Source Path",
                            kind="string",
                            required=True,
                            help_text="Absolute path to the source Parquet data file",
                        ),
                        ParameterDefinition(
                            name="max_rows",
                            label="Max Rows (Head Limit)",
                            kind="integer",
                            required=False,
                            help_text="Read only the first N rows as a head limit (None = no limit). This is NOT sampling: the first rows are taken in file order and may not represent the full dataset distribution.",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        source_path = params.get("source_path")
        if not source_path:
            errors.append("source_path is required")
            return errors
        src = Path(source_path)
        if not src.exists():
            errors.append(f"source_path does not exist: {source_path}")
            return errors
        if src.suffix.lower() != ".parquet":
            errors.append(
                f"Unsupported file format {src.suffix!r}; the import boundary accepts Parquet only"
            )
        max_rows = params.get("max_rows")
        if max_rows is not None:
            if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
                errors.append(f"max_rows must be a positive integer, got {max_rows!r}")
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        source_path = Path(params["source_path"])
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Import source_path does not exist or is not a file: {source_path}")
        if source_path.suffix.lower() != ".parquet":
            raise ValueError(
                f"Unsupported file format {source_path.suffix!r}; the import boundary accepts Parquet only"
            )

        max_rows: int | None = params.get("max_rows")
        df = pl.read_parquet(source_path, n_rows=max_rows)

        if df.is_empty():
            raise ValueError(f"Import produced zero rows from {source_path.name}")

        metadata: dict[str, Any] = {}
        warnings: list[JsonDict] = []

        if max_rows is not None:
            metadata["max_rows_applied"] = max_rows
            warnings.append({
                "code": "SOURCE_ROW_LIMIT_APPLIED",
                "message": f"Imported only the first {max_rows} rows (head limit). This is not "
                           f"sampling: the head rows may not represent the full dataset distribution.",
            })

        art_metadata = {
            "source_file": source_path.name,
            "format": "parquet",
            "columns": list(df.columns),
            "row_count": df.height,
        }
        art_metadata.update(metadata)

        context.outputs.publish_table(
            role="input",
            kind=EvidenceKind.MODELLING_METADATA,
            frame=df,
            metadata=art_metadata,
        )
        for w in warnings:
            context.outputs.add_warning(w)
        context.outputs.add_metric("row_count", df.height)
        context.outputs.add_metric("column_count", df.width)
        return context.outputs.build_result()
