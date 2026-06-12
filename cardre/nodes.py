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
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input"]
    output_roles: list[str] = ["train", "test", "oot"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        input_artifact = context.input_artifacts[0]
        store = context.store
        params = context.validated_params

        train_frac = float(params.get("train_fraction", 0.6))
        test_frac = float(params.get("test_fraction", 0.2))
        oot_frac = float(params.get("oot_fraction", 0.2))
        seed = int(params.get("random_seed", 42))

        total = train_frac + test_frac + oot_frac
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Split fractions sum to {total}, expected 1.0")

        df = pl.read_parquet(store.artifact_path(input_artifact))
        n = df.height
        indices = list(range(n))

        import random as rng
        rng.seed(seed)
        rng.shuffle(indices)

        n_train = int(n * train_frac)
        n_test = int(n * test_frac)
        train_idx = indices[:n_train]
        test_idx = indices[n_train : n_train + n_test]
        oot_idx = indices[n_train + n_test :]

        artifacts = []
        for role, idx_list, frac_name in [
            ("train", train_idx, train_frac),
            ("test", test_idx, test_frac),
            ("oot", oot_idx, oot_frac),
        ]:
            subset = df[idx_list]
            table_logical = table_logical_hash(subset)
            buf = io.BytesIO()
            subset.write_parquet(buf, statistics=False, compression="zstd")
            parquet_bytes = buf.getvalue()
            parquet_path = store.root / "datasets" / f"{table_logical[:16]}-{role}.parquet"
            parquet_path.parent.mkdir(parents=True, exist_ok=True)
            parquet_path.write_bytes(parquet_bytes)

            phys = physical_hash(parquet_path)
            artifact_id = str(uuid.uuid4())
            artifact = ArtifactRef(
                artifact_id=artifact_id,
                artifact_type="dataset",
                role=role,
                path=relative_path(parquet_path, store.root),
                physical_hash=phys,
                logical_hash=table_logical,
                media_type="application/vnd.apache.parquet",
                metadata={
                    "source_artifact_id": input_artifact.artifact_id,
                    "split_params": params,
                    "role": role,
                    "row_count": len(idx_list),
                },
            )
            store.register_artifact(artifact)
            artifacts.append(artifact)

        logical_hashes = [a.logical_hash for a in artifacts]
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
            artifacts=artifacts,
            metrics={
                "train_count": len(train_idx),
                "test_count": len(test_idx),
                "oot_count": len(oot_idx),
            },
            execution_fingerprint=fingerprint,
        )


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
