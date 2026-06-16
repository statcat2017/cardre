from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import polars as pl

from cardre.artifacts import make_fingerprint, write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
)
from cardre.evidence import SCHEMA_MODELLING_METADATA


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
    node_type = "cardre.import_dataset"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["input"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not params.get("source_path"):
            errors.append("source_path is required")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        params = context.validated_params
        source_path = Path(params["source_path"])
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Import source_path does not exist or is not a file: {source_path}")
        if source_path.suffix.lower() not in (".zip", ".data", ".txt"):
            raise ValueError(
                "cardre.import_dataset currently supports only UCI German Credit "
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

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[artifact],
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height, "column_count": df.width},
            execution_fingerprint=fingerprint,
        )

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


class ProfileDatasetNode(NodeType):
    node_type = "cardre.profile_dataset"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "test", "oot"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        input_artifact = context.input_artifacts[0]

        path = store.artifact_path(input_artifact)
        df = pl.read_parquet(path)

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

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[artifact],
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height},
            execution_fingerprint=fingerprint,
        )

    def _numeric_stats(self, df: pl.DataFrame) -> dict[str, dict[str, float]]:
        stats = {}
        for col in df.columns:
            if df.schema[col] in (pl.Float64, pl.Float32, pl.Int64, pl.Int32, pl.Int16, pl.Int8, pl.UInt32, pl.UInt16, pl.UInt8):
                series = df[col]
                if series.drop_nulls().is_empty():
                    stats[col] = {"min": None, "max": None, "mean": None, "std": None}
                    continue
                stats[col] = {
                    "min": float(series.min()),
                    "max": float(series.max()),
                    "mean": float(series.mean()),
                    "std": float(series.std()),
                }
        return stats


class ValidateBinaryTargetNode(NodeType):
    node_type = "cardre.validate_binary_target"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        input_artifact = context.input_artifacts[0]
        params = context.validated_params
        target_col = params.get("target_column", "credit_risk_class")

        df = pl.read_parquet(store.artifact_path(input_artifact))
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

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[artifact],
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"is_binary": report["is_binary"]},
            execution_fingerprint=fingerprint,
        )


class SplitTrainTestOotNode(NodeType):
    node_type = "cardre.split_train_test_oot"
    version = "2"
    category = "transform"
    input_roles: list[str] = ["input", "definition"]
    output_roles: list[str] = ["train", "test", "oot"]

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

        df = pl.read_parquet(store.artifact_path(dataset_artifact))

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
        write_json_artifact(
            store,
            artifact_type="report",
            role="report",
            stem=f"split-report-{context.step_spec.step_id}",
            payload=split_report,
            metadata={"source_artifact_id": dataset_artifact.artifact_id},
        )

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=artifacts,
        )

        return NodeOutput(
            artifacts=artifacts,
            metrics={
                "train_count": role_map["train"].height,
                "test_count": role_map["test"].height,
                "oot_count": role_map["oot"].height,
            },
            execution_fingerprint=fingerprint,
        )

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
        df = pl.read_parquet(store.artifact_path(dataset_artifact))

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

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[artifact],
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"target_column": target_column},
            execution_fingerprint=fingerprint,
        )


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
        write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"exclusion-report-{context.step_spec.step_id}",
            payload=exclusion_report,
            metadata={"source_artifact_id": dataset_artifact.artifact_id},
        )

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[dataset_artifact],
        )

        return NodeOutput(
            artifacts=[dataset_artifact],
            metrics={"rows_before": n_before, "rows_after": df.height},
            execution_fingerprint=fingerprint,
        )


class DevelopmentSampleDefinitionNode(NodeType):
    node_type = "cardre.development_sample_definition"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "definition"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:

        store = context.store
        params = context.validated_params

        weight_column = params.get("weight_column")
        if weight_column:
            dataset_artifact = next(a for a in context.input_artifacts if a.role in ("input", "train"))
            df = pl.read_parquet(store.artifact_path(dataset_artifact))
            if weight_column not in df.columns:
                raise ValueError(f"Weight column '{weight_column}' not found in dataset")
            if not df.schema[weight_column].is_numeric():
                raise ValueError(f"Weight column '{weight_column}' must be numeric")

        sample_def = {
            "sample_method": params.get("sample_method", "full_population"),
            "weight_column": weight_column,
            "population_bad_rate": params.get("population_bad_rate"),
            "prior_probability_adjustment": params.get("prior_probability_adjustment"),
        }

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"sample-definition-{context.step_spec.step_id}",
            payload=sample_def,
            metadata={},
        )

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[artifact],
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"sample_method": sample_def["sample_method"]},
            execution_fingerprint=fingerprint,
        )


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
            df = pl.read_parquet(store.artifact_path(input_art))
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

        write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"treatment-report-{context.step_spec.step_id}",
            payload=treatment_report,
            metadata={},
        )

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=output_artifacts,
        )

        return NodeOutput(
            artifacts=output_artifacts,
            metrics={"output_count": len(output_artifacts)},
            execution_fingerprint=fingerprint,
        )