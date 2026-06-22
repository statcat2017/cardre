from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
)
from cardre.evidence import SCHEMA_MODELLING_METADATA, SCHEMA_SAMPLE_DEFINITION
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)


GERMAN_CREDIT_COLUMNS = [
    "checking_account_status",
    "duration_months",
    "credit_history",
    "purpose",
    "credit_amount",
    "savings_account_bonds",
    "present_employment_since",
    "installment_rate_percent_disposable_income",
    "personal_status_sex",
    "other_debtors_guarantors",
    "present_residence_since",
    "property",
    "age_years",
    "other_installment_plans",
    "housing",
    "existing_credits_at_bank",
    "job",
    "people_liable_maintenance",
    "telephone",
    "foreign_worker",
    "credit_risk_class",
]


class ImportGermanCreditNode(NodeType):
    node_type = "cardre.import_fixture_uci_german_credit"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["input"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        source_path = params.get("source_path")
        if not source_path:
            errors.append("source_path is required")
            return errors
        src = Path(source_path)
        if not src.exists():
            errors.append(f"source_path does not exist: {source_path}")
        elif src.suffix.lower() not in (".zip", ".data", ".txt"):
            errors.append(f"source_path must be .zip, .data, or .txt, got {src.suffix!r}")
        else:
            try:
                if src.suffix == ".zip":
                    with zipfile.ZipFile(src) as zf:
                        names = zf.namelist()
                        data_file = next((n for n in names if Path(n).name == "german.data"), None)
                        if data_file is None:
                            errors.append("ZIP file must contain 'german.data'")
                else:
                    content = src.read_text(encoding="latin-1")
                    first_line = content.strip().split("\n")[0]
                    if first_line:
                        field_count = len(first_line.split())
                        if field_count != 21:
                            errors.append(
                                f"Expected 21 fields per row, got {field_count}. "
                                f"File may not be German Credit format."
                            )
            except Exception as exc:
                errors.append(f"Cannot read source file: {exc}")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        params = context.validated_params
        source_path = Path(params["source_path"])
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Import source_path does not exist or is not a file: {source_path}")
        if source_path.suffix.lower() not in (".zip", ".data", ".txt"):
            raise ValueError(
                "ImportGermanCreditNode (cardre.import_fixture_uci_german_credit) supports only "
                f"'.data', '.txt', or '.zip' sources, got {source_path.suffix!r}"
            )
        artifact_metadata = {
            "source_dataset_id": "uci-statlog-german-credit",
            "target_column": "credit_risk_class",
            "target_mapping": {"1": "good", "2": "bad"},
            "source_file": source_path.name,
        }

        if source_path.suffix == ".zip":
            df = self._read_from_zip(source_path)
        else:
            df = self._read_from_file(source_path)

        store = context.store

        artifact = write_parquet_artifact(
            store,
            artifact_type="dataset",
            role="input",
            stem="german-credit",
            frame=df,
            metadata=artifact_metadata,
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height, "column_count": df.width})

    def _read_from_zip(self, zip_path: Path) -> pl.DataFrame:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            data_file = next((n for n in names if Path(n).name == "german.data"), None)
            if data_file is None:
                raise ValueError("German Credit ZIP import requires a file named 'german.data'")
            content = zf.read(data_file).decode("latin-1")
        return self._parse_content(content)

    def _read_from_file(self, file_path: Path) -> pl.DataFrame:
        content = file_path.read_text(encoding="latin-1")
        return self._parse_content(content)

    def _parse_content(self, content: str) -> pl.DataFrame:
        rows = []
        malformed: list[tuple[int, int]] = []
        for line_no, line in enumerate(content.strip().split("\n"), start=1):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 21:
                rows.append(parts)
            else:
                malformed.append((line_no, len(parts)))
        if malformed:
            details = ", ".join(f"line {line_no}: {field_count} fields" for line_no, field_count in malformed[:10])
            raise ValueError(
                f"German Credit import expected 21 whitespace-delimited fields per row; malformed rows: {details}"
            )
        if not rows:
            raise ValueError("German Credit import produced zero rows")
        return pl.DataFrame(
            data=rows,
            schema=GERMAN_CREDIT_COLUMNS,
            orient="row",
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
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        params = context.validated_params
        source_path = Path(params["source_path"])
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Import source_path does not exist or is not a file: {source_path}")

        fmt = self._resolve_format(params, source_path)
        if fmt == "parquet":
            df = pl.read_parquet(source_path)  # cardre-allow-artifact-read: dataset-frame-input
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
            )

        if df.is_empty():
            raise ValueError(f"Import produced zero rows from {source_path.name}")

        store = context.store

        artifact = write_parquet_artifact(
            store,
            artifact_type="dataset",
            role="input",
            stem="imported-dataset",
            frame=df,
            metadata={
                "source_file": source_path.name,
                "format": fmt,
                "columns": list(df.columns),
                "row_count": df.height,
            },
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height, "column_count": df.width},
        )

    @staticmethod
    def _resolve_format(params: dict[str, Any], src: Path) -> str:
        fmt = params.get("format", "auto")
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


class ProfileDatasetNode(NodeType):
    node_type = "cardre.profile_dataset"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "test", "oot"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        input_artifact = context.input_artifacts[0]

        path = store.artifact_path(input_artifact)  # cardre-allow-artifact-read: dataset-frame-input
        df = pl.read_parquet(path)  # cardre-allow-artifact-read: dataset-frame-input

        report = {
            "row_count": df.height,
            "column_count": df.width,
            "columns": list(df.columns),
            "dtypes": {c: str(df.schema[c]) for c in df.columns},
            "null_counts": {c: int(df[c].null_count()) for c in df.columns},
            "numeric_stats": self._numeric_stats(df),
            "profile_steps": [],
        }

        artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"profile-{context.step_spec.step_id}",
            payload=report,
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height})

    def _numeric_stats(self, df: pl.DataFrame) -> dict[str, dict[str, float]]:
        numeric_cols = [c for c in df.columns if df.schema[c].is_numeric()]
        if not numeric_cols:
            return {}

        empty_cols = {c for c in numeric_cols if df[c].drop_nulls().is_empty()}
        available = [c for c in numeric_cols if c not in empty_cols]

        stats = {c: {"min": None, "max": None, "mean": None, "std": None} for c in numeric_cols}

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


class ValidateBinaryTargetNode(NodeType):
    node_type = "cardre.validate_binary_target"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train"]
    output_roles: list[str] = ["report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Validate Binary Target",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="target_column",
                            label="Target Column",
                            kind="string",
                            default="credit_risk_class",
                            help_text="Name of the column containing the binary target",
                        ),
                        ParameterDefinition(
                            name="min_class_fraction",
                            label="Minimum Class Fraction",
                            kind="float",
                            default=0.05,
                            constraint=ParameterConstraint(
                                min_value=0.0,
                                max_value=1.0,
                            ),
                            help_text="Minimum allowed fraction of the minority class",
                        ),
                        ParameterDefinition(
                            name="max_class_ratio",
                            label="Maximum Class Ratio",
                            kind="float",
                            default=20.0,
                            constraint=ParameterConstraint(
                                min_value=1.0,
                            ),
                            help_text="Maximum allowed ratio of majority count to minority count",
                        ),
                        ParameterDefinition(
                            name="strict",
                            label="Strict Validation",
                            kind="boolean",
                            default=True,
                            help_text="If true, raise an error when validation constraints are violated",
                        ),
                    ],
                ),
            ],
        )

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        input_artifact = context.input_artifacts[0]
        params = context.validated_params
        target_col = params.get("target_column", "credit_risk_class")

        df = pl.read_parquet(store.artifact_path(input_artifact))  # cardre-allow-artifact-read: dataset-frame-input
        values = df[target_col].unique().to_list()
        unique_values = sorted(str(v) for v in values)

        report = {
            "target_column": target_col,
            "unique_values": unique_values,
            "count": len(unique_values),
            "is_binary": len(unique_values) == 2,
            "value_counts": {
                str(k): int(v)
                for k, v in df[target_col].value_counts().rows()
            },
            "null_count": int(df[target_col].null_count()),
        }

        if len(unique_values) != 2:
            raise ValueError(
                f"Target column {target_col!r} has {len(unique_values)} unique values, expected 2"
            )

        artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"target-validate-{context.step_spec.step_id}",
            payload=report,
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"is_binary": report["is_binary"]})


class SplitTrainTestOotNode(NodeType):
    node_type = "cardre.split_train_test_oot"
    version = "2"
    category = "transform"
    input_roles: list[str] = ["input", "definition"]
    output_roles: list[str] = ["train", "test", "oot"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        fraction_constraint = ParameterConstraint(min_value=0.0, max_value=1.0)
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Split Train / Test / OOT",
            methods=[
                MethodOption(
                    id="random_stratified",
                    label="Random Stratified Split",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="train_fraction",
                            label="Train Fraction",
                            kind="float",
                            default=0.6,
                            constraint=fraction_constraint,
                            help_text="Fraction of rows allocated to the training set",
                        ),
                        ParameterDefinition(
                            name="test_fraction",
                            label="Test Fraction",
                            kind="float",
                            default=0.2,
                            constraint=fraction_constraint,
                            help_text="Fraction of rows allocated to the test set",
                        ),
                        ParameterDefinition(
                            name="oot_fraction",
                            label="OOT Fraction",
                            kind="float",
                            default=0.2,
                            constraint=fraction_constraint,
                            help_text="Fraction of rows allocated to the out-of-time validation set",
                        ),
                        ParameterDefinition(
                            name="random_seed",
                            label="Random Seed",
                            kind="integer",
                            default=42,
                            constraint=ParameterConstraint(min_value=0),
                            help_text="Seed for reproducible shuffling",
                        ),
                        ParameterDefinition(
                            name="target_column",
                            label="Target Column",
                            kind="string",
                            default="credit_risk_class",
                            help_text="Name of the target column for stratified splitting",
                        ),
                    ],
                ),
                MethodOption(
                    id="preassigned_role_column",
                    label="Preassigned Role Column",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="role_column",
                            label="Role Column",
                            kind="string",
                            required=True,
                            help_text="Name of a column with preassigned role values ('train', 'test', 'oot')",
                        ),
                    ],
                ),
            ],
        )

    def run(self, context: ExecutionContext) -> NodeOutput:

        dataset_artifact = next(a for a in context.input_artifacts if a.role == "input")
        store = context.store
        params = context.validated_params

        strategy = params.get("strategy", "random_stratified")
        train_frac = float(params.get("train_fraction", 0.6))
        test_frac = float(params.get("test_fraction", 0.2))
        oot_frac = float(params.get("oot_fraction", 0.2))
        seed = int(params.get("random_seed", 42))
        target_column = params.get("target_column", "credit_risk_class")
        role_column = params.get("role_column")

        total = train_frac + test_frac + oot_frac
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Split fractions sum to {total}, expected 1.0")

        df = pl.read_parquet(store.artifact_path(dataset_artifact))  # cardre-allow-artifact-read: dataset-frame-input

        if strategy == "preassigned_role_column":
            if not role_column or role_column not in df.columns:
                raise ValueError(f"preassigned_role_column '{role_column}' not found in dataset")
            role_map = {}
            for role_val in ("train", "test", "oot"):
                mask = df[role_column] == role_val
                count = mask.sum()
                if count == 0:
                    raise ValueError(f"Role column {role_column} has no rows with value '{role_val}'")
                role_map[role_val] = df[mask]
        elif strategy == "random_stratified":
            if target_column not in df.columns:
                raise ValueError(f"Target column '{target_column}' not found in dataset")
            role_map = self._stratified_split(df, target_column, train_frac, test_frac, oot_frac, seed)
        else:
            raise ValueError(f"Unknown split strategy: {strategy}")

        artifacts = []
        for role in ("train", "test", "oot"):
            subset = role_map[role]
            artifact = write_parquet_artifact(
                store,
                artifact_type="dataset",
                role=role,
                stem=f"split-{role}",
                frame=subset,
                metadata={
                    "source_artifact_id": dataset_artifact.artifact_id,
                    "strategy": strategy,
                    "row_count": subset.height,
                },
            )
            artifacts.append(artifact)

        target_rates = {}
        split_warnings = []
        for role, subset in role_map.items():
            if subset.height == 0:
                split_warnings.append({
                    "code": "EMPTY_SPLIT_ROLE",
                    "message": f"Split role {role!r} has zero rows; increase sample size or adjust fractions",
                    "role": role,
                })
            if target_column in subset.columns:
                col = subset[target_column]
                vals = col.value_counts()
                target_rates[role] = {str(r[0]): int(r[1]) for r in vals.iter_rows()}
        if target_column in role_map["train"].columns:
            train_classes = role_map["train"][target_column].drop_nulls().unique().to_list()
            if len(train_classes) < 2:
                raise ValueError(
                    f"Train split has {len(train_classes)} non-null target class(es), expected at least 2"
                )

        split_report = {
            "strategy": strategy,
            "random_seed": seed if strategy != "preassigned_role_column" else None,
            "fractions": {"train": train_frac, "test": test_frac, "oot": oot_frac},
            "row_counts": {role: subset.height for role, subset in role_map.items()},
            "target_rates": target_rates,
            "warnings": split_warnings,
            "source_artifact_id": dataset_artifact.artifact_id,
        }
        split_report_artifact = write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"split-report-{context.step_spec.step_id}",
            payload=split_report,
            metadata={"source_artifact_id": dataset_artifact.artifact_id},
        )
        artifacts.append(split_report_artifact)

        return NodeOutput(
            artifacts=artifacts,
            metrics={
                "train_count": role_map["train"].height,
                "test_count": role_map["test"].height,
                "oot_count": role_map["oot"].height,
            })

    def _stratified_split(
        self,
        df: pl.DataFrame,
        target_column: str,
        train_frac: float,
        test_frac: float,
        oot_frac: float,
        seed: int,
    ) -> dict[str, pl.DataFrame]:
        import random as rng
        rng.seed(seed)

        df_with_idx = df.with_columns(pl.Series("__row_idx__", range(df.height)))
        groups = df_with_idx.group_by(target_column).agg(pl.col("__row_idx__"))

        train_indices: list[int] = []
        test_indices: list[int] = []
        oot_indices: list[int] = []

        for row in groups.iter_rows():
            group_indices = list(row[1])
            rng.shuffle(group_indices)
            n = len(group_indices)
            n_train = max(1, int(n * train_frac))
            n_test = max(1, int(n * test_frac))
            train_indices.extend(group_indices[:n_train])
            test_indices.extend(group_indices[n_train:n_train + n_test])
            oot_indices.extend(group_indices[n_train + n_test:])

        return {
            "train": df[train_indices],
            "test": df[test_indices],
            "oot": df[oot_indices],
        }


class DefineModellingMetadataNode(NodeType):
    node_type = "cardre.define_modelling_metadata"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params
        dataset_artifact = context.input_artifacts[0]
        df = pl.read_parquet(store.artifact_path(dataset_artifact))  # cardre-allow-artifact-read: dataset-frame-input

        target_column = params.get("target_column", "")
        good_values = params.get("good_values", [])
        bad_values = params.get("bad_values", [])
        indeterminate_values = params.get("indeterminate_values", [])

        if not target_column:
            raise ValueError("Target column must be non-empty")
        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in dataset")
        if not good_values:
            raise ValueError("Good values must be non-empty")
        if not bad_values:
            raise ValueError("Bad values must be non-empty")
        good_value_strings = {str(v) for v in good_values}
        bad_value_strings = {str(v) for v in bad_values}
        indeterminate_value_strings = {str(v) for v in indeterminate_values}
        overlap = good_value_strings & bad_value_strings
        if overlap:
            raise ValueError(f"Good and bad value sets overlap: {overlap}")
        observed_values = {str(v) for v in df[target_column].drop_nulls().unique().to_list()}
        declared_values = good_value_strings | bad_value_strings | indeterminate_value_strings
        missing_declared = sorted((good_value_strings | bad_value_strings) - observed_values)
        if missing_declared:
            raise ValueError(
                f"Good/bad metadata values do not match target column {target_column!r}: "
                f"declared values absent from data: {missing_declared}"
            )
        undeclared_observed = sorted(observed_values - declared_values)
        if undeclared_observed:
            raise ValueError(
                f"Target column {target_column!r} contains values not declared as good, bad, "
                f"or indeterminate: {undeclared_observed}"
            )

        metadata = {
            "target_column": target_column,
            "good_values": good_values,
            "bad_values": bad_values,
            "indeterminate_values": indeterminate_values,
            "population": params.get("population", ""),
            "product": params.get("product", ""),
            "segment": params.get("segment", ""),
            "observation_window": params.get("observation_window"),
            "performance_window": params.get("performance_window"),
        }

        metadata["schema_version"] = SCHEMA_MODELLING_METADATA
        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"modelling-metadata-{context.step_spec.step_id}",
            payload=metadata,
            metadata={"source_artifact_id": dataset_artifact.artifact_id, "schema_version": SCHEMA_MODELLING_METADATA},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"target_column": target_column})


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

        df = pl.read_parquet(store.artifact_path(dataset_artifact))  # cardre-allow-artifact-read: dataset-frame-input
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

            n_before_rule = df.height
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
            n_after_rule = df.height
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
            metadata={"source_artifact_id": dataset_artifact.artifact_id},
        )

        return NodeOutput(
            artifacts=[dataset_artifact, exclusion_report_artifact],
            metrics={"rows_before": n_before, "rows_after": df.height})


class DevelopmentSampleDefinitionNode(NodeType):
    node_type = "cardre.development_sample_definition"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "definition"]
    output_roles: list[str] = ["definition"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        domain = params.get("sample_domain", "ttd")
        if domain not in ("ttd", "otb"):
            errors.append("sample_domain must be 'ttd' or 'otb'")
        if domain == "ttd":
            rejection_source = params.get("rejection_source")
            if rejection_source is not None and rejection_source not in ("flag_column", "target_missing"):
                errors.append("rejection_source must be 'flag_column', 'target_missing', or None")
        if domain == "otb":
            if not params.get("approval_column"):
                errors.append("approval_column is required for otb sample domain")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params

        sample_domain = params.get("sample_domain", "ttd")
        rejection_source = params.get("rejection_source")
        rejection_column = params.get("rejection_column")
        rejection_values = params.get("rejection_values")
        approval_column = params.get("approval_column")
        approval_values = params.get("approval_values", [])
        weight_column = params.get("weight_column")

        dataset_artifact = next(a for a in context.input_artifacts if a.role in ("input", "train"))
        df = pl.read_parquet(store.artifact_path(dataset_artifact))  # cardre-allow-artifact-read: dataset-frame-input
        total_rows = df.height

        if weight_column:
            if weight_column not in df.columns:
                raise ValueError(f"Weight column '{weight_column}' not found in dataset")
            if not df.schema[weight_column].is_numeric():
                raise ValueError(f"Weight column '{weight_column}' must be numeric")

        sample_def = {
            "schema_version": SCHEMA_SAMPLE_DEFINITION,
            "sample_method": params.get("sample_method", "full_population"),
            "weight_column": weight_column,
            "population_bad_rate": params.get("population_bad_rate"),
            "prior_probability_adjustment": params.get("prior_probability_adjustment"),
            "sample_domain": sample_domain,
            "total_rows": total_rows,
            "financed_rows": 0,
            "non_financed_rows": 0,
            "rejection_source": rejection_source,
            "rejection_column": rejection_column,
            "rejection_values": rejection_values,
            "approval_column": approval_column,
            "approval_values": approval_values,
            "sample_description": params.get("sample_description", ""),
        }

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"sample-definition-{context.step_spec.step_id}",
            payload=sample_def,
            metadata={"schema_version": SCHEMA_SAMPLE_DEFINITION},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"sample_method": sample_def["sample_method"]})


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

        treatment_report = {"imputations": {}, "caps": {}, "floors": {}}

        output_artifacts = []
        for input_art in context.input_artifacts:
            df = pl.read_parquet(store.artifact_path(input_art))  # cardre-allow-artifact-read: dataset-frame-input
            affected = {"imputations": {}, "caps": {}, "floors": {}}

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
