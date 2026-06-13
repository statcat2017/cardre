"""Proof node implementations for Phase 1.

These are minimal implementations to exercise the executor, role enforcement,
and artifact lifecycle. Phase 2+ will replace these with real scorecard nodes.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import polars as pl

from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    NodeOutput,
    NodeType,
    json_logical_hash,
    params_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
    utc_now_iso,
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
    node_type = "cardre.import_dataset"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["input"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        params = context.validated_params
        source_path = Path(params["source_path"])
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

        artifact_metadata["row_count"] = df.height
        artifact_metadata["column_count"] = df.width

        table_logical = table_logical_hash(df)
        store = context.store

        buf = io.BytesIO()
        df.write_parquet(buf, statistics=False, compression="zstd")
        parquet_bytes = buf.getvalue()
        parquet_path = store.root / "datasets" / f"{table_logical[:16]}-german-credit.parquet"
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        parquet_path.write_bytes(parquet_bytes)

        phys = physical_hash(parquet_path)
        artifact_id = str(uuid.uuid4())
        artifact = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="dataset",
            role="input",
            path=relative_path(parquet_path, store.root),
            physical_hash=phys,
            logical_hash=table_logical,
            media_type="application/vnd.apache.parquet",
            metadata=artifact_metadata,
        )
        store.register_artifact(artifact)

        fingerprint = {
            "plan_version_id": context.plan_version_id,
            "step_id": context.step_spec.step_id,
            "node_type": self.node_type,
            "node_version": self.version,
            "params_hash": context.step_spec.params_hash,
            "parent_run_step_ids": [],
            "input_artifact_logical_hashes": [],
            "output_artifact_logical_hashes": [table_logical],
        }

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height, "column_count": df.width},
            execution_fingerprint=fingerprint,
        )

    def _read_from_zip(self, zip_path: Path) -> pl.DataFrame:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            data_file = next((n for n in names if n.endswith("german.data")), None)
            if data_file is None:
                data_file = next((n for n in names if "german" in n.lower()), None)
            if data_file is None:
                data_file = names[0]
            content = zf.read(data_file).decode("latin-1")
        return self._parse_content(content)

    def _read_from_file(self, file_path: Path) -> pl.DataFrame:
        content = file_path.read_text(encoding="latin-1")
        return self._parse_content(content)

    def _parse_content(self, content: str) -> pl.DataFrame:
        rows = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 21:
                rows.append(parts)
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
        input_artifact = context.input_artifacts[0]
        store = context.store

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

        report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
        logical = json_logical_hash(report)
        report_path = (
            store.root / "artifacts" / f"{logical[:16]}-profile-{context.step_spec.step_id}.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(report_bytes)

        phys = physical_hash(report_path)
        artifact_id = str(uuid.uuid4())
        artifact = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="report",
            role="report",
            path=relative_path(report_path, store.root),
            physical_hash=phys,
            logical_hash=logical,
            media_type="application/json",
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )
        store.register_artifact(artifact)

        fingerprint = {
            "plan_version_id": context.plan_version_id,
            "step_id": context.step_spec.step_id,
            "node_type": self.node_type,
            "node_version": self.version,
            "params_hash": context.step_spec.params_hash,
            "parent_run_step_ids": [rs.run_step_id for rs in context.parent_run_steps],
            "input_artifact_logical_hashes": [a.logical_hash for a in context.input_artifacts],
            "output_artifact_logical_hashes": [logical],
        }

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
        input_artifact = context.input_artifacts[0]
        store = context.store
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

        report_bytes = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
        logical = json_logical_hash(report)
        report_path = (
            store.root / "artifacts" / f"{logical[:16]}-target-validate-{context.step_spec.step_id}.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_bytes(report_bytes)

        phys = physical_hash(report_path)
        artifact_id = str(uuid.uuid4())
        artifact = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="report",
            role="report",
            path=relative_path(report_path, store.root),
            physical_hash=phys,
            logical_hash=logical,
            media_type="application/json",
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )
        store.register_artifact(artifact)

        fingerprint = {
            "plan_version_id": context.plan_version_id,
            "step_id": context.step_spec.step_id,
            "node_type": self.node_type,
            "node_version": self.version,
            "params_hash": context.step_spec.params_hash,
            "parent_run_step_ids": [rs.run_step_id for rs in context.parent_run_steps],
            "input_artifact_logical_hashes": [a.logical_hash for a in context.input_artifacts],
            "output_artifact_logical_hashes": [logical],
        }

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
        from cardre.artifacts import make_fingerprint, write_json_artifact, write_parquet_artifact

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
        for role, subset in role_map.items():
            if target_column in subset.columns:
                col = subset[target_column]
                vals = col.value_counts()
                target_rates[role] = {str(r[0]): int(r[1]) for r in vals.iter_rows()}

        split_report = {
            "strategy": strategy,
            "random_seed": seed if strategy != "preassigned_role_column" else None,
            "fractions": {"train": train_frac, "test": test_frac, "oot": oot_frac},
            "row_counts": {role: subset.height for role, subset in role_map.items()},
            "target_rates": target_rates,
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


class DummyFitNode(NodeType):
    node_type = "cardre.dummy_fit"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        input_artifact = context.input_artifacts[0]
        store = context.store
        params = context.validated_params

        df = pl.read_parquet(store.artifact_path(input_artifact))
        dummy_def = {
            "model_type": "dummy",
            "version": self.version,
            "params": params,
            "input_columns": list(df.columns),
            "row_count": df.height,
        }

        report_bytes = json.dumps(dummy_def, indent=2, sort_keys=True).encode("utf-8")
        logical = json_logical_hash(dummy_def)
        def_path = (
            store.root / "artifacts" / f"{logical[:16]}-dummy-fit-{context.step_spec.step_id}.json"
        )
        def_path.parent.mkdir(parents=True, exist_ok=True)
        def_path.write_bytes(report_bytes)

        phys = physical_hash(def_path)
        artifact_id = str(uuid.uuid4())
        artifact = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type="definition",
            role="definition",
            path=relative_path(def_path, store.root),
            physical_hash=phys,
            logical_hash=logical,
            media_type="application/json",
            metadata={"source_artifact_id": input_artifact.artifact_id},
        )
        store.register_artifact(artifact)

        fingerprint = {
            "plan_version_id": context.plan_version_id,
            "step_id": context.step_spec.step_id,
            "node_type": self.node_type,
            "node_version": self.version,
            "params_hash": context.step_spec.params_hash,
            "parent_run_step_ids": [rs.run_step_id for rs in context.parent_run_steps],
            "input_artifact_logical_hashes": [a.logical_hash for a in context.input_artifacts],
            "output_artifact_logical_hashes": [logical],
        }

        return NodeOutput(
            artifacts=[artifact],
            metrics={"row_count": df.height},
            execution_fingerprint=fingerprint,
        )


class DummyApplyNode(NodeType):
    node_type = "cardre.dummy_apply"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["prediction"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        data_artifacts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        def_artifact = next((a for a in context.input_artifacts if a.role == "definition"), None)

        if def_artifact is None:
            raise ValueError("Dummy apply requires a definition artifact")

        input_roles = {a.role for a in data_artifacts}
        required_roles = {"train", "test", "oot"}
        missing = required_roles - input_roles
        if missing:
            raise ValueError(
                f"Dummy apply requires train, test, and oot artifacts. "
                f"Missing: {sorted(missing)}. "
                f"Received roles: {sorted(input_roles)}"
            )

        outputs = []
        for data_art in data_artifacts:
            df = pl.read_parquet(store.artifact_path(data_art))
            pred = pl.DataFrame({
                "dummy_prediction": [0.5] * df.height,
                "row_id": list(range(df.height)),
            })

            table_logical = table_logical_hash(pred)
            buf = io.BytesIO()
            pred.write_parquet(buf, statistics=False, compression="zstd")
            parquet_bytes = buf.getvalue()
            fname = f"{table_logical[:16]}-apply-{data_art.role}-{context.step_spec.step_id}.parquet"
            pred_path = store.root / "artifacts" / fname
            pred_path.parent.mkdir(parents=True, exist_ok=True)
            pred_path.write_bytes(parquet_bytes)

            phys = physical_hash(pred_path)
            artifact_id = str(uuid.uuid4())
            artifact = ArtifactRef(
                artifact_id=artifact_id,
                artifact_type="dataset",
                role="prediction",
                path=relative_path(pred_path, store.root),
                physical_hash=phys,
                logical_hash=table_logical,
                media_type="application/vnd.apache.parquet",
                metadata={
                    "source_artifact_id": data_art.artifact_id,
                    "definition_artifact_id": def_artifact.artifact_id,
                },
            )
            store.register_artifact(artifact)
            outputs.append(artifact)

        logical_hashes = [a.logical_hash for a in outputs]
        fingerprint = {
            "plan_version_id": context.plan_version_id,
            "step_id": context.step_spec.step_id,
            "node_type": self.node_type,
            "node_version": self.version,
            "params_hash": context.step_spec.params_hash,
            "parent_run_step_ids": [rs.run_step_id for rs in context.parent_run_steps],
            "input_artifact_logical_hashes": [a.logical_hash for a in context.input_artifacts],
            "output_artifact_logical_hashes": logical_hashes,
        }

        return NodeOutput(
            artifacts=outputs,
            metrics={"output_count": len(outputs)},
            execution_fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# Phase 2A: Define Modelling Metadata
# ---------------------------------------------------------------------------

class DefineModellingMetadataNode(NodeType):
    node_type = "cardre.define_modelling_metadata"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact

        store = context.store
        params = context.validated_params
        dataset_artifact = context.input_artifacts[0]
        df = pl.read_parquet(store.artifact_path(dataset_artifact))

        target_column = params.get("target_column", "")
        good_values = params.get("good_values", [])
        bad_values = params.get("bad_values", [])

        if target_column and target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in dataset")
        if not good_values:
            raise ValueError("Good values must be non-empty")
        if not bad_values:
            raise ValueError("Bad values must be non-empty")
        overlap = set(good_values) & set(bad_values)
        if overlap:
            raise ValueError(f"Good and bad value sets overlap: {overlap}")

        metadata = {
            "target_column": target_column,
            "good_values": good_values,
            "bad_values": bad_values,
            "indeterminate_values": params.get("indeterminate_values", []),
            "population": params.get("population", ""),
            "product": params.get("product", ""),
            "segment": params.get("segment", ""),
            "observation_window": params.get("observation_window"),
            "performance_window": params.get("performance_window"),
        }

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"modelling-metadata-{context.step_spec.step_id}",
            payload=metadata,
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
            output_artifacts=[artifact],
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"target_column": target_column},
            execution_fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# Phase 2A: Apply Exclusions
# ---------------------------------------------------------------------------

class ApplyExclusionsNode(NodeType):
    node_type = "cardre.apply_exclusions"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "definition"]
    output_roles: list[str] = ["input", "train"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact, write_parquet_artifact

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
                df = df.filter(col_expr == value)
            elif operator == "!=":
                df = df.filter(col_expr != value)
            elif operator == "<":
                df = df.filter(col_expr < value)
            elif operator == "<=":
                df = df.filter(col_expr <= value)
            elif operator == ">":
                df = df.filter(col_expr > value)
            elif operator == ">=":
                df = df.filter(col_expr >= value)
            elif operator == "in":
                df = df.filter(col_expr.is_in(value))
            elif operator == "not_in":
                df = df.filter(~col_expr.is_in(value))
            elif operator == "is_null":
                df = df.filter(col_expr.is_null())
            elif operator == "is_not_null":
                df = df.filter(col_expr.is_not_null())
            n_after_rule = df.height
            rule_counts.append({
                "column": column,
                "operator": operator,
                "value": value,
                "reason": reason,
                "rows_removed": n_before_rule - n_after_rule,
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


# ---------------------------------------------------------------------------
# Phase 2A: Development Sample Definition
# ---------------------------------------------------------------------------

class DevelopmentSampleDefinitionNode(NodeType):
    node_type = "cardre.development_sample_definition"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "definition"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact

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


# ---------------------------------------------------------------------------
# Phase 2A: Explicit Missing/Outlier Treatment
# ---------------------------------------------------------------------------

class ExplicitMissingOutlierTreatmentNode(NodeType):
    node_type = "cardre.explicit_missing_outlier_treatment"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot"]
    output_roles: list[str] = ["train", "test", "oot"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact, write_parquet_artifact

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


# ---------------------------------------------------------------------------
# Phase 2A: Fine Classing
# ---------------------------------------------------------------------------

class FineClassingNode(NodeType):
    node_type = "cardre.fine_classing"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact

        store = context.store
        params = context.validated_params
        max_bins = int(params.get("max_bins", 20))
        min_bin_fraction = float(params.get("min_bin_fraction", 0.05))
        missing_policy = params.get("missing_policy", "separate_bin")
        max_categorical_levels = int(params.get("max_categorical_levels", 50))
        exclude_columns = list(params.get("exclude_columns", []))

        if max_bins < 2:
            raise ValueError("max_bins must be >= 2")
        if not (0 < min_bin_fraction < 1):
            raise ValueError("min_bin_fraction must be between 0 and 1")

        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        meta_artifact = next((a for a in context.input_artifacts if a.role == "definition"), None)

        df = pl.read_parquet(store.artifact_path(train_artifact))

        if meta_artifact:
            meta_path = store.artifact_path(meta_artifact)
            meta = json.loads(meta_path.read_text())
            target_column = meta.get("target_column", "")
            good_values = set(str(v) for v in meta.get("good_values", []))
            bad_values = set(str(v) for v in meta.get("bad_values", []))
        else:
            target_column = ""
            good_values = set()
            bad_values = set()

        if target_column and target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found")
        if target_column:
            exclude_columns = list(set(exclude_columns + [target_column]))

        feature_cols = [c for c in df.columns if c not in exclude_columns]

        variables = []
        warnings: list[dict] = []

        for col in feature_cols:
            col_dtype = df.schema[col]
            is_numeric = col_dtype in (
                pl.Float64, pl.Float32, pl.Int64, pl.Int32,
                pl.Int16, pl.Int8, pl.UInt64, pl.UInt32, pl.UInt16, pl.UInt8,
            )

            if is_numeric:
                bins = self._bin_numeric(df, col, target_column, good_values, bad_values,
                                         max_bins, min_bin_fraction, missing_policy, warnings)
                variables.append({
                    "variable": col,
                    "kind": "numeric",
                    "bins": bins,
                })
            else:
                bins = self._bin_categorical(df, col, target_column, good_values, bad_values,
                                             max_categorical_levels, missing_policy, warnings)
                variables.append({
                    "variable": col,
                    "kind": "categorical",
                    "bins": bins,
                })

        bin_def = {
            "variables": variables,
            "warnings": warnings,
        }

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"fine-classing-{context.step_spec.step_id}",
            payload=bin_def,
            metadata={
                "source_artifact_id": train_artifact.artifact_id,
                "target_column": target_column,
            },
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
            metrics={"variable_count": len(variables)},
            execution_fingerprint=fingerprint,
        )

    def _bin_numeric(
        self, df: pl.DataFrame, col: str, target_column: str,
        good_values: set, bad_values: set,
        max_bins: int, min_bin_fraction: float,
        missing_policy: str, warnings: list[dict],
    ) -> list[dict]:
        non_null = df.filter(pl.col(col).is_not_null())
        missing = df.filter(pl.col(col).is_null())

        bins = []
        bin_counter = 0

        if missing.height > 0 and missing_policy == "separate_bin":
            bin_counter += 1
            missing_bin = self._make_bin_counts(missing, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "Missing",
                "lower": None,
                "upper": None,
                "lower_inclusive": False,
                "upper_inclusive": False,
                "categories": None,
                "is_missing_bin": True,
                "row_count": missing_bin["row_count"],
                "good_count": missing_bin["good_count"],
                "bad_count": missing_bin["bad_count"],
            })

        if non_null.height == 0:
            return bins

        values = non_null[col].to_list()
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        n_bins = min(max_bins, n)
        bin_size = max(1, n // n_bins)

        for i in range(0, n, bin_size):
            if len(bins) - (1 if missing.height > 0 and missing_policy == "separate_bin" else 0) >= max_bins:
                break
            chunk = sorted_vals[i:i + bin_size]
            lower = chunk[0]
            upper = chunk[-1]
            if i > 0:
                lower = sorted_vals[i]
            mask = (pl.col(col).is_not_null()) & (pl.col(col) >= lower) & (pl.col(col) <= upper)
            # For the last bin, include everything above
            if i + bin_size >= n:
                mask = (pl.col(col).is_not_null()) & (pl.col(col) >= lower)

            bin_df = non_null.filter(
                (pl.col(col) >= lower) & (pl.col(col) <= upper)
            ) if i + bin_size < n else non_null.filter(pl.col(col) >= lower)

            bin_counter += 1
            bin_counts = self._make_bin_counts(bin_df, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": f"({lower:.4g}, {upper:.4g}]" if i + bin_size < n else f"({lower:.4g}, +inf)",
                "lower": lower,
                "upper": upper if i + bin_size < n else None,
                "lower_inclusive": False,
                "upper_inclusive": True,
                "categories": None,
                "is_missing_bin": False,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
            })

        total_n = non_null.height
        for b in bins:
            if not b.get("is_missing_bin") and total_n > 0:
                frac = b["row_count"] / total_n
                if frac < min_bin_fraction:
                    warnings.append({
                        "variable": col,
                        "bin_id": b["bin_id"],
                        "message": f"Bin fraction {frac:.4f} is below min_bin_fraction {min_bin_fraction}",
                    })

        if bin_counter == 0 and non_null.height > 0:
            bin_counter += 1
            bin_counts = self._make_bin_counts(non_null, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "All values",
                "lower": None,
                "upper": None,
                "lower_inclusive": False,
                "upper_inclusive": False,
                "categories": None,
                "is_missing_bin": False,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
            })

        return bins

    def _bin_categorical(
        self, df: pl.DataFrame, col: str, target_column: str,
        good_values: set, bad_values: set,
        max_categorical_levels: int, missing_policy: str,
        warnings: list[dict],
    ) -> list[dict]:
        non_null = df.filter(pl.col(col).is_not_null())
        missing = df.filter(pl.col(col).is_null())

        value_counts = non_null[col].value_counts().sort(col, descending=True)
        all_levels = value_counts[col].to_list()

        other_categories: list = []
        if len(all_levels) > max_categorical_levels:
            top_levels = all_levels[:max_categorical_levels]
            other_categories = all_levels[max_categorical_levels:]
            warnings.append({
                "variable": col,
                "message": f"High cardinality: {len(all_levels)} categories, "
                          f"using top {max_categorical_levels} plus 'Other'",
                "dropped_categories": len(other_categories),
            })
            all_levels = top_levels

        bins = []
        bin_counter = 0

        if missing.height > 0 and missing_policy == "separate_bin":
            bin_counter += 1
            bin_counts = self._make_bin_counts(missing, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "Missing",
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": None,
                "is_missing_bin": True,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
            })

        for level in all_levels:
            bin_counter += 1
            bin_df = non_null.filter(pl.col(col) == level)
            count = bin_df.height
            if count == 0:
                continue
            bin_counts = self._make_bin_counts(bin_df, col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": str(level),
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": [level],
                "is_missing_bin": False,
                "row_count": bin_counts["row_count"],
                "good_count": bin_counts["good_count"],
                "bad_count": bin_counts["bad_count"],
            })

        if other_categories:
            bin_counter += 1
            other_df = non_null.filter(pl.col(col).is_in(other_categories))
            if other_df.height > 0:
                bin_counts = self._make_bin_counts(other_df, col, target_column, good_values, bad_values)
                bins.append({
                    "bin_id": f"{col}_bin_{bin_counter:03d}",
                    "label": "Other",
                    "lower": None, "upper": None,
                    "lower_inclusive": False, "upper_inclusive": False,
                    "categories": other_categories,
                    "is_missing_bin": False,
                    "row_count": bin_counts["row_count"],
                    "good_count": bin_counts["good_count"],
                    "bad_count": bin_counts["bad_count"],
                })

        return bins

    def _make_bin_counts(
        self, bin_df: pl.DataFrame, col: str, target_column: str,
        good_values: set, bad_values: set,
    ) -> dict:
        row_count = bin_df.height
        if target_column and target_column in bin_df.columns and (good_values or bad_values):
            target_series = bin_df[target_column].cast(pl.String)
            good_count = int(target_series.is_in(list(good_values)).sum()) if good_values else 0
            bad_count = int(target_series.is_in(list(bad_values)).sum()) if bad_values else 0
        else:
            good_count = 0
            bad_count = 0
        return {"row_count": row_count, "good_count": good_count, "bad_count": bad_count}


# ---------------------------------------------------------------------------
# Phase 2A: Calculate WOE / IV
# ---------------------------------------------------------------------------

class CalculateWoeIvNode(NodeType):
    node_type = "cardre.calculate_woe_iv"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact, write_parquet_artifact

        store = context.store
        params = context.validated_params
        zero_cell_policy = params.get("zero_cell_policy", "block")
        smoothing = params.get("smoothing")
        purpose = params.get("purpose", "initial")

        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        bin_artifact = next(a for a in context.input_artifacts if a.role == "definition")

        df = pl.read_parquet(store.artifact_path(train_artifact))
        bin_def_raw = json.loads(store.artifact_path(bin_artifact).read_text())

        meta_def = None
        for a in context.input_artifacts:
            if a.role == "definition" and a.artifact_id != bin_artifact.artifact_id:
                meta_def = json.loads(store.artifact_path(a).read_text())
                break

        target_column = (meta_def or {}).get("target_column", "")
        good_values = set(str(v) for v in (meta_def or {}).get("good_values", []))
        bad_values = set(str(v) for v in (meta_def or {}).get("bad_values", []))

        if target_column and target_column in df.columns:
            target_series = df[target_column].cast(pl.String)
        else:
            target_series = None

        woe_rows: list[dict] = []
        iv_rows: dict[str, dict] = {}
        warnings_list: list[dict] = []

        for var_def in bin_def_raw.get("variables", []):
            variable = var_def["variable"]
            kind = var_def["kind"]
            bins = var_def["bins"]

            if variable not in df.columns:
                continue

            col_values = df[variable]

            total_good = 0
            total_bad = 0
            if target_series is not None and good_values and bad_values:
                if kind == "numeric":
                    total_good = int(target_series.is_in(list(good_values)).sum())
                    total_bad = int(target_series.is_in(list(bad_values)).sum())
                else:
                    total_good = int(target_series.is_in(list(good_values)).sum())
                    total_bad = int(target_series.is_in(list(bad_values)).sum())

            var_woe_rows = []
            var_iv = 0.0
            zero_cell_count = 0

            for bin_def in bins:
                bin_id = bin_def["bin_id"]
                label = bin_def["label"]
                is_missing = bin_def.get("is_missing_bin", False)

                if kind == "numeric":
                    lower = bin_def.get("lower")
                    upper = bin_def.get("upper")
                    lower_inc = bin_def.get("lower_inclusive", False)
                    upper_inc = bin_def.get("upper_inclusive", True)

                    if is_missing:
                        bin_mask = col_values.is_null()
                    else:
                        conditions = []
                        if lower is not None:
                            conditions.append(col_values >= lower if lower_inc else col_values > lower)
                        if upper is not None:
                            conditions.append(col_values <= upper if upper_inc else col_values < upper)
                        bin_mask = conditions[0] if len(conditions) == 1 else conditions[0]
                        for c in conditions[1:]:
                            bin_mask = bin_mask & c
                else:
                    categories = bin_def.get("categories", [])
                    if is_missing:
                        bin_mask = col_values.is_null()
                    elif categories:
                        bin_mask = col_values.is_in(categories)
                    else:
                        bin_mask = pl.Series([False] * df.height)

                row_count = int(bin_mask.sum())

                if target_series is not None and good_values and bad_values:
                    bin_good = int(target_series.filter(bin_mask).is_in(list(good_values)).sum())
                    bin_bad = int(target_series.filter(bin_mask).is_in(list(bad_values)).sum())
                else:
                    bin_good = bin_def.get("good_count", 0)
                    bin_bad = bin_def.get("bad_count", 0)

                good_dist = bin_good / total_good if total_good > 0 else 0.0
                bad_dist = bin_bad / total_bad if total_bad > 0 else 0.0

                if good_dist == 0.0 or bad_dist == 0.0:
                    zero_cell_count += 1
                    if zero_cell_policy == "block" and purpose == "final":
                        if smoothing and smoothing.get("method") == "additive":
                            alpha = float(smoothing.get("alpha", 0.5))
                            if not smoothing.get("rationale"):
                                raise ValueError(
                                    f"Zero cell in variable {variable!r} bin {bin_id!r}: "
                                    f"smoothing configured without a rationale"
                                )
                            good_dist = (bin_good + alpha) / (total_good + alpha * len(bins)) if total_good > 0 else alpha / (alpha * len(bins))
                            bad_dist = (bin_bad + alpha) / (total_bad + alpha * len(bins)) if total_bad > 0 else alpha / (alpha * len(bins))
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
                        good_dist = (bin_good + alpha) / (total_good + alpha * len(bins)) if total_good > 0 else alpha / (alpha * len(bins))
                        bad_dist = (bin_bad + alpha) / (total_bad + alpha * len(bins)) if total_bad > 0 else alpha / (alpha * len(bins))

                if good_dist == 0.0 or bad_dist == 0.0:
                    woe_val = 0.0
                    iv_comp = 0.0
                else:
                    woe_val = float(__import__("math").log(good_dist / bad_dist))
                    iv_comp = (good_dist - bad_dist) * woe_val

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

            woe_rows.extend(var_woe_rows)
            iv_rows[variable] = {
                "variable": variable,
                "iv": round(var_iv, 6),
                "bin_count": len(bins),
                "zero_cell_count": zero_cell_count,
                "warning_count": sum(1 for w in warnings_list if w["variable"] == variable),
            }

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
            metadata={"purpose": purpose, "zero_cell_policy": zero_cell_policy},
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
        write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"woe-summary-{purpose}-{context.step_spec.step_id}",
            payload=summary,
            metadata={"purpose": purpose},
        )

        fingerprint = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type,
            node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[woe_art, iv_art],
        )

        return NodeOutput(
            artifacts=[woe_art, iv_art],
            metrics={"variable_count": len(iv_rows)},
            execution_fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# Phase 2A: Variable Clustering
# ---------------------------------------------------------------------------

class VariableClusteringNode(NodeType):
    node_type = "cardre.variable_clustering"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "report"]
    output_roles: list[str] = ["report"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact

        store = context.store
        params = context.validated_params
        correlation_threshold = float(params.get("correlation_threshold", 0.7))
        candidate_limit = int(params.get("candidate_limit", 50))

        if not (0 < correlation_threshold < 1):
            raise ValueError("correlation_threshold must be between 0 and 1")

        train_artifact = next(a for a in context.input_artifacts if a.role == "train")
        iv_artifact = next((a for a in context.input_artifacts if a.role == "report"), None)

        df = pl.read_parquet(store.artifact_path(train_artifact))
        numeric_cols = [c for c in df.columns if df.schema[c].is_numeric()]
        numeric_cols = numeric_cols[:candidate_limit]

        clusters: list[dict] = []
        warnings: list[dict] = []

        if len(numeric_cols) < 2:
            for col in numeric_cols:
                clusters.append({
                    "cluster_id": f"singleton_{col}",
                    "variables": [col],
                    "reason": "Insufficient numeric columns for correlation clustering",
                })
            if numeric_cols:
                warnings.append({
                    "message": f"Only {len(numeric_cols)} numeric candidate(s); clustering is pass-through",
                })
        else:
            try:
                import numpy as np
                corr_matrix = df.select(numeric_cols).to_numpy()
                if corr_matrix.shape[1] == 0:
                    raise ValueError("Empty correlation matrix")
                corr = np.corrcoef(corr_matrix.T)

                assigned = set()
                cluster_id = 0
                for i, col_i in enumerate(numeric_cols):
                    if i in assigned:
                        continue
                    cluster_members = [col_i]
                    assigned.add(i)
                    for j, col_j in enumerate(numeric_cols):
                        if j in assigned or i == j:
                            continue
                        if abs(corr[i, j]) >= correlation_threshold:
                            cluster_members.append(col_j)
                            assigned.add(j)
                    cluster_id += 1
                    clusters.append({
                        "cluster_id": f"cluster_{cluster_id:03d}",
                        "variables": cluster_members,
                        "reason": f"Correlation >= {correlation_threshold}" if len(cluster_members) > 1
                                  else "Singleton (no correlated peers)",
                    })

                unassigned = [c for c in numeric_cols
                             if numeric_cols.index(c) not in assigned]
                for col in unassigned:
                    clusters.append({
                        "cluster_id": f"singleton_{col}",
                        "variables": [col],
                        "reason": "Singleton (not in any correlation cluster)",
                    })

            except (ImportError, ValueError):
                for col in numeric_cols:
                    clusters.append({
                        "cluster_id": f"singleton_{col}",
                        "variables": [col],
                        "reason": "Clustering unavailable (numpy not available); pass-through",
                    })
                warnings.append({"message": "Correlation clustering unavailable; using singleton pass-through"})

        clustering_report = {
            "correlation_threshold": correlation_threshold,
            "candidate_limit": candidate_limit,
            "total_candidates": len(numeric_cols),
            "clusters": clusters,
            "warnings": warnings,
        }

        artifact = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"clustering-{context.step_spec.step_id}",
            payload=clustering_report,
            metadata={"candidate_count": len(numeric_cols)},
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
            metrics={"cluster_count": len(clusters)},
            execution_fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# Phase 2A: Variable Selection
# ---------------------------------------------------------------------------

class VariableSelectionNode(NodeType):
    node_type = "cardre.variable_selection"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["report"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact

        store = context.store
        params = context.validated_params
        min_iv = float(params.get("min_iv", 0.02))
        max_variables = int(params.get("max_variables", 15))
        manual_includes_raw = list(params.get("manual_includes", []))
        manual_excludes_raw = list(params.get("manual_excludes", []))
        manual_includes = [v if isinstance(v, str) else v.get("variable", "") for v in manual_includes_raw]
        manual_excludes = [v if isinstance(v, str) else v.get("variable", "") for v in manual_excludes_raw]
        manual_include_reasons = {
            v["variable"]: v.get("reason", "Manual inclusion")
            for v in manual_includes_raw if not isinstance(v, str)
        }
        manual_exclude_reasons = {
            v["variable"]: v.get("reason", "Manual exclusion")
            for v in manual_excludes_raw if not isinstance(v, str)
        }

        iv_artifact = None
        clustering_artifact = None
        for a in context.input_artifacts:
            if a.role != "report":
                continue
            try:
                content = store.artifact_path(a).read_bytes()
                if content[:4] == b"PAR1":
                    temp_df = pl.read_parquet(store.artifact_path(a))
                    if "iv" in temp_df.columns and "variable" in temp_df.columns:
                        iv_artifact = a
                else:
                    clustering_artifact = a
            except Exception:
                continue

        if iv_artifact:
            iv_df = pl.read_parquet(store.artifact_path(iv_artifact))
            iv_cols = iv_df.columns
            iv_map = {}
            for row in iv_df.iter_rows():
                iv_map[str(row[iv_cols.index("variable")])] = {
                    "iv": float(row[iv_cols.index("iv")]),
                    "bin_count": int(row[iv_cols.index("bin_count")]),
                    "zero_cell_count": int(row[iv_cols.index("zero_cell_count")]),
                }
        else:
            iv_map = {}

        clusters = []
        if clustering_artifact:
            try:
                raw = store.artifact_path(clustering_artifact).read_bytes()
                if raw[:4] != b"PAR1":
                    clustering_raw = json.loads(raw)
                    clusters = clustering_raw.get("clusters", [])
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        cluster_map: dict[str, str] = {}
        for cl in clusters:
            for var in cl.get("variables", []):
                cluster_map[var] = cl["cluster_id"]

        candidates = sorted(iv_map.keys(), key=lambda v: iv_map[v]["iv"], reverse=True)
        selected: list[dict] = []
        rejected: list[dict] = []
        seen_clusters: set[str] = set()

        for var in candidates:
            if var in manual_excludes:
                reason = manual_exclude_reasons.get(var, "Manual exclusion")
                rejected.append({"variable": var, "reason": reason})
                continue

        for var in candidates:
            if var in manual_excludes:
                continue
            if var in manual_includes:
                reason = manual_include_reasons.get(var, "Manual inclusion")
                selected.append({"variable": var, "reason": reason})
                seen_clusters.add(cluster_map.get(var, var))
                continue

            iv_info = iv_map[var]
            if iv_info["iv"] < min_iv:
                rejected.append({
                    "variable": var,
                    "reason": f"IV {iv_info['iv']:.4f} below threshold {min_iv}",
                })
                continue

            cluster_id = cluster_map.get(var, var)
            if cluster_id in seen_clusters:
                rejected.append({
                    "variable": var,
                    "reason": f"Lower IV than selected correlated variable in cluster {cluster_id}",
                })
                continue

            if len(selected) >= max_variables:
                rejected.append({
                    "variable": var,
                    "reason": f"Reached max_variables limit ({max_variables})",
                })
                continue

            selected.append({
                "variable": var,
                "reason": f"IV above threshold and strongest in cluster"
                         if cluster_id not in seen_clusters else
                         f"IV above threshold",
            })
            seen_clusters.add(cluster_id)

        selection = {
            "min_iv": min_iv,
            "max_variables": max_variables,
            "selected": selected,
            "rejected": rejected,
        }

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"variable-selection-{context.step_spec.step_id}",
            payload=selection,
            metadata={"selected_count": len(selected), "rejected_count": len(rejected)},
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
            metrics={"selected_count": len(selected), "rejected_count": len(rejected)},
            execution_fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# Phase 2A: Manual Binning
# ---------------------------------------------------------------------------

class ManualBinningNode(NodeType):
    node_type = "cardre.manual_binning"
    version = "1"
    category = "refinement"
    input_roles: list[str] = ["definition"]
    output_roles: list[str] = ["definition"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact

        store = context.store
        params = context.validated_params
        overrides = params.get("overrides", [])

        bin_artifact = next(a for a in context.input_artifacts if a.role == "definition")
        selection_artifact = next((a for a in context.input_artifacts
                                   if a.role == "definition" and a.artifact_id != bin_artifact.artifact_id),
                                  None)

        bin_def = json.loads(store.artifact_path(bin_artifact).read_text())
        selected_vars = set()
        if selection_artifact:
            sel = json.loads(store.artifact_path(selection_artifact).read_text())
            selected_vars = {s["variable"] for s in sel.get("selected", [])}

        var_map = {v["variable"]: v for v in bin_def.get("variables", [])}

        warnings: list[dict] = []

        for override in overrides:
            variable = override.get("variable", "")
            action = override.get("action", "")
            reason = override.get("reason", "")
            if not reason:
                raise ValueError(f"Override for '{variable}' requires a non-empty reason")
            if variable not in var_map:
                raise ValueError(f"Override references unknown variable '{variable}'")
            if action not in ("merge_bins", "group_categories", "isolate_missing", "isolate_special_value"):
                raise ValueError(f"Unsupported manual_binning action '{action}'")

            source_bin_ids = override.get("source_bin_ids", [])
            var_bins = var_map[variable]["bins"]
            bin_id_map = {b["bin_id"]: b for b in var_bins}

            for bid in source_bin_ids:
                if bid not in bin_id_map:
                    raise ValueError(f"bin_id '{bid}' not found in variable '{variable}'")

            if action == "merge_bins":
                if len(source_bin_ids) < 2:
                    raise ValueError(f"merge_bins requires at least 2 source bins, got {len(source_bin_ids)}")
                kind = var_map[variable].get("kind", "")
                if kind == "numeric":
                    bin_positions = [var_bins.index(bin_id_map[bid]) for bid in source_bin_ids]
                    expected_positions = list(range(min(bin_positions), max(bin_positions) + 1))
                    if bin_positions != expected_positions:
                        raise ValueError(
                            f"Numeric bin merge for {variable!r} requires adjacent bins. "
                            f"Source bins at positions {bin_positions} are not contiguous. "
                            f"Expected adjacent positions {expected_positions}"
                        )
                new_label = override.get("new_label", "Merged")
                merged = {
                    "bin_id": f"{variable}_manual_{override.get('new_label', 'merged').lower().replace(' ', '_')}",
                    "label": new_label,
                    "lower": bin_id_map[source_bin_ids[0]].get("lower"),
                    "upper": bin_id_map[source_bin_ids[-1]].get("upper"),
                    "lower_inclusive": bin_id_map[source_bin_ids[0]].get("lower_inclusive", False),
                    "upper_inclusive": bin_id_map[source_bin_ids[-1]].get("upper_inclusive", True),
                    "categories": None,
                    "is_missing_bin": False,
                    "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                    "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                    "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
                }
                new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
                new_bins.insert(
                    min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids),
                    merged,
                )
                var_map[variable]["bins"] = new_bins

            elif action == "group_categories":
                new_label = override.get("new_label", "Grouped")
                grouped = {
                    "bin_id": f"{variable}_manual_grouped",
                    "label": new_label,
                    "lower": None, "upper": None,
                    "lower_inclusive": False, "upper_inclusive": False,
                    "categories": sum([bin_id_map[bid].get("categories", []) for bid in source_bin_ids], []),
                    "is_missing_bin": False,
                    "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                    "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                    "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
                }
                new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
                new_bins.insert(
                    min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids),
                    grouped,
                )
                var_map[variable]["bins"] = new_bins

        # Filter to only selected variables if selection artifact exists
        if selected_vars:
            var_map = {k: v for k, v in var_map.items() if k in selected_vars}

        if not overrides:
            warnings.append({"message": "No manual overrides applied; passing through auto bins for selected variables"})

        refined = {
            "variables": list(var_map.values()),
            "warnings": bin_def.get("warnings", []) + warnings,
        }

        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"manual-binning-{context.step_spec.step_id}",
            payload=refined,
            metadata={"override_count": len(overrides)},
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
            metrics={"override_count": len(overrides)},
            execution_fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# Phase 2A: Technical Manifest Export (stub)
# ---------------------------------------------------------------------------

class TechnicalManifestExportNode(NodeType):
    node_type = "cardre.technical_manifest_export"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["definition", "report"]
    output_roles: list[str] = ["manifest"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        from cardre.artifacts import make_fingerprint, write_json_artifact

        store = context.store
        run_id = context.run_id
        plan_version_id = context.plan_version_id

        run = store.get_run(run_id)
        plan_version = store.get_plan_version(plan_version_id)
        plan = None
        project = None
        if plan_version:
            plan_id_result = store._connect().execute(
                "SELECT plan_id FROM plan_versions WHERE plan_version_id = ?",
                (plan_version_id,),
            ).fetchone()
            if plan_id_result:
                plan = store.get_plan(plan_id_result["plan_id"])
                if plan:
                    project = store.get_project(plan["project_id"])

        all_run_steps = store.get_run_steps(run_id)

        steps_evidence = []
        artifacts_evidence = []
        all_warnings: list[dict] = []
        all_errors: list[dict] = []

        seen_artifact_ids: set[str] = set()
        for rs in all_run_steps:
            step_info = {
                "step_id": rs.step_id,
                "node_type": rs.execution_fingerprint.get("node_type", ""),
                "node_version": rs.execution_fingerprint.get("node_version", ""),
                "status": rs.status,
                "params_hash": rs.execution_fingerprint.get("params_hash", ""),
                "input_artifact_logical_hashes": rs.execution_fingerprint.get("input_artifact_logical_hashes", []),
                "output_artifact_logical_hashes": rs.execution_fingerprint.get("output_artifact_logical_hashes", []),
            }
            steps_evidence.append(step_info)

            for aid in rs.output_artifact_ids:
                if aid in seen_artifact_ids:
                    continue
                seen_artifact_ids.add(aid)
                art = store.get_artifact(aid)
                if art:
                    artifacts_evidence.append({
                        "artifact_id": art.artifact_id,
                        "artifact_type": art.artifact_type,
                        "role": art.role,
                        "physical_hash": art.physical_hash,
                        "logical_hash": art.logical_hash,
                        "media_type": art.media_type,
                    })
            for w in rs.warnings:
                all_warnings.append(dict(w))
            for e in rs.errors:
                all_errors.append(dict(e))

        modelling_metadata = {}
        selected_variables = []

        for rs in all_run_steps:
            if rs.execution_fingerprint.get("node_type") == "cardre.define_modelling_metadata":
                for aid in rs.output_artifact_ids:
                    art = store.get_artifact(aid)
                    if art:
                        try:
                            modelling_metadata = json.loads(store.artifact_path(art).read_text())
                        except (FileNotFoundError, json.JSONDecodeError):
                            pass
            if rs.execution_fingerprint.get("node_type") == "cardre.variable_selection":
                for aid in rs.output_artifact_ids:
                    art = store.get_artifact(aid)
                    if art:
                        try:
                            sel = json.loads(store.artifact_path(art).read_text())
                            selected_variables = sel.get("selected", [])
                        except (FileNotFoundError, json.JSONDecodeError):
                            pass

        manifest = {
            "project": {
                "project_id": project["project_id"] if project else "",
                "name": project["name"] if project else "",
            } if project else {},
            "run": {
                "run_id": run_id,
                "plan_version_id": plan_version_id,
            },
            "steps": steps_evidence,
            "artifacts": artifacts_evidence,
            "modelling_metadata": modelling_metadata,
            "selected_variables": selected_variables,
            "warnings": all_warnings,
            "errors": all_errors,
        }

        artifact = write_json_artifact(
            store, artifact_type="manifest", role="manifest",
            stem=f"technical-manifest-{context.step_spec.step_id}",
            payload=manifest,
            metadata={"run_id": run_id, "plan_version_id": plan_version_id},
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
            metrics={"step_count": len(steps_evidence), "artifact_count": len(artifacts_evidence)},
            execution_fingerprint=fingerprint,
        )
