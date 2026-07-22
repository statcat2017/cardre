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
    ParameterConstraint,
    ParameterDefinition,
)

_DTYPE_MAP: dict[str, type[pl.DataType]] = {
    "str": pl.Utf8, "string": pl.Utf8, "utf8": pl.Utf8, "Utf8": pl.Utf8,
    "int": pl.Int64, "Int64": pl.Int64, "integer": pl.Int64,
    "float": pl.Float64, "Float64": pl.Float64, "double": pl.Float64, "f64": pl.Float64,
    "bool": pl.Boolean, "boolean": pl.Boolean, "Bool": pl.Boolean,
}


class ImportTabularDatasetNode(NodeType):
    node_type = "cardre.import_dataset"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["input"]

    __definition__ = NodeDefinition(
        node_type="cardre.import_dataset",
        version="1",
        category="transform",
        description="Import tabular dataset from file",
        input_contract=ArtifactContract(),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=("dataset",)),)),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    SUPPORTED_FORMATS = frozenset({"csv", "tsv", "parquet"})

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        encoding_constraint = ParameterConstraint(enum_values=["utf-8", "latin-1", "utf-16", "ascii"])
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
                            help_text="Absolute path to the source data file (CSV, TSV, or Parquet)",
                        ),
                        ParameterDefinition(
                            name="format",
                            label="Format",
                            kind="string",
                            default="auto",
                            constraint=ParameterConstraint(
                                enum_values=["auto", "csv", "tsv", "parquet"],
                            ),
                            help_text="File format override. 'auto' infers from file extension",
                        ),
                        ParameterDefinition(
                            name="delimiter",
                            label="Delimiter",
                            kind="string",
                            required=False,
                            help_text="Column delimiter for text files. Inferred from format if omitted",
                        ),
                        ParameterDefinition(
                            name="has_header",
                            label="Has Header Row",
                            kind="boolean",
                            default=True,
                            help_text="Whether the first row contains column headers",
                        ),
                        ParameterDefinition(
                            name="encoding",
                            label="File Encoding",
                            kind="string",
                            default="utf-8",
                            constraint=encoding_constraint,
                            help_text="Character encoding of the source file",
                        ),
                        ParameterDefinition(
                            name="null_values",
                            label="Null Values",
                            kind="list",
                            default=[],
                            help_text="List of strings to treat as null values during import",
                        ),
                        ParameterDefinition(
                            name="schema_overrides",
                            label="Schema Overrides",
                            kind="object",
                            default={},
                            help_text="Dict mapping column names to dtype strings, e.g. {'age': 'int', 'income': 'float'}",
                        ),
                        ParameterDefinition(
                            name="max_rows",
                            label="Max Rows",
                            kind="integer",
                            required=False,
                            help_text="Maximum rows to read (None = no limit). Useful for sampling large files.",
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
        fmt = self._resolve_format(params, src)
        if fmt not in self.SUPPORTED_FORMATS:
            errors.append(
                f"Unsupported format {fmt!r}; supported: {', '.join(sorted(self.SUPPORTED_FORMATS))}"
            )
        schema_overrides_raw = params.get("schema_overrides", {})
        if schema_overrides_raw:
            if not isinstance(schema_overrides_raw, dict):
                errors.append("schema_overrides must be a dict mapping column names to dtype strings")
            else:
                for col, dtype_str in schema_overrides_raw.items():
                    if not isinstance(dtype_str, str) or dtype_str not in _DTYPE_MAP:
                        valid = sorted(_DTYPE_MAP)
                        errors.append(
                            f"Unrecognised dtype {dtype_str!r} for column {col!r}; "
                            f"supported: {valid}"
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

        max_rows: int | None = params.get("max_rows")
        fmt = self._resolve_format(params, source_path)
        if fmt == "parquet":
            df = pl.read_parquet(source_path, n_rows=max_rows)
        else:
            delimiter = params.get("delimiter")
            if not delimiter:
                delimiter = "\t" if fmt == "tsv" else ","
            has_header = params.get("has_header", True)
            encoding = params.get("encoding", "utf-8")
            null_values = params.get("null_values", [])
            schema_overrides_raw = params.get("schema_overrides", {})
            schema_overrides = {}
            if schema_overrides_raw:
                schema_overrides = {
                    col: _DTYPE_MAP[dtype_str]
                    for col, dtype_str in schema_overrides_raw.items()
                }
            df = pl.read_csv(
                source_path,
                separator=delimiter,
                has_header=has_header,
                encoding=encoding,
                null_values=null_values if null_values else None,
                schema_overrides=schema_overrides or None,
                infer_schema_length=10000,
                n_rows=max_rows,
            )

        if df.is_empty():
            raise ValueError(f"Import produced zero rows from {source_path.name}")

        metadata: dict[str, Any] = {}
        warnings: list[JsonDict] = []

        if max_rows is not None:
            metadata["max_rows_applied"] = max_rows
            warnings.append({
                "code": "SOURCE_ROW_LIMIT_APPLIED",
                "message": f"Imported at most {max_rows} rows. The first {max_rows} rows may not "
                           f"represent the full dataset distribution.",
            })

        art_metadata = {
            "source_file": source_path.name,
            "format": fmt,
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

    @staticmethod
    def _resolve_format(params: dict[str, Any], src: Path) -> str:
        fmt = str(params.get("format", "auto"))
        if fmt != "auto":
            return fmt
        suffix = src.suffix.lower()
        if suffix in (".csv",):
            return "csv"
        if suffix in (".tsv",):
            return "tsv"
        if suffix in (".parquet",):
            return "parquet"
        return suffix.lstrip(".") if suffix else "unknown"
