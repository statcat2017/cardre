from __future__ import annotations

import numpy as np
import polars as pl

from cardre._evidence.schemas import SCHEMA_SPLIT_SUMMARY
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType
from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)


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
            default_method="random_stratified",
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
        method = params.get("method", "random_stratified")
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

        if method == "preassigned_role_column":
            if not role_column or role_column not in df.columns:
                raise ValueError(f"Role column '{role_column}' not found in dataset for 'preassigned_role_column' method")
            role_map = {}
            for role_val in ("train", "test", "oot"):
                mask = df[role_column] == role_val
                count = mask.sum()
                if count == 0:
                    raise ValueError(f"Role column {role_column} has no rows with value '{role_val}'")
                role_map[role_val] = df[mask]
        elif method == "random_stratified":
            if target_column not in df.columns:
                raise ValueError(f"Target column '{target_column}' not found in dataset")
            role_map = self._stratified_split(df, target_column, train_frac, test_frac, oot_frac, seed)
        else:
            raise ValueError(f"Unknown split method: {method}")

        artifacts = []
        for role in ("train", "test", "oot"):
            subset = role_map[role]
            artifact = write_parquet_artifact(
                store, artifact_type="dataset", role=role, stem=f"split-{role}", frame=subset,
                metadata={"source_artifact_id": dataset_artifact.artifact_id, "method": method, "row_count": subset.height},
            )
            artifacts.append(artifact)

        target_rates = {}
        split_warnings = []
        for role, subset in role_map.items():
            if subset.height == 0:
                split_warnings.append({"code": "EMPTY_SPLIT_ROLE", "message": f"Split role {role!r} has zero rows; increase sample size or adjust fractions", "role": role})
            if target_column in subset.columns:
                col = subset[target_column]
                vals = col.value_counts()
                target_rates[role] = {str(r[0]): int(r[1]) for r in vals.iter_rows()}
        if target_column in role_map["train"].columns:
            train_classes = role_map["train"][target_column].drop_nulls().unique().to_list()
            if len(train_classes) < 2:
                raise ValueError(f"Train split has {len(train_classes)} non-null target class(es), expected at least 2")

        split_report = {
            "method": method,
            "random_seed": seed if method != "preassigned_role_column" else None,
            "fractions": {"train": train_frac, "test": test_frac, "oot": oot_frac},
            "row_counts": {role: subset.height for role, subset in role_map.items()},
            "target_rates": target_rates, "warnings": split_warnings,
            "source_artifact_id": dataset_artifact.artifact_id,
        }
        split_report_artifact = write_json_artifact(
            store, artifact_type="report", role="report", stem=f"split-report-{context.step_spec.step_id}",
            payload=split_report,
            metadata={"source_artifact_id": dataset_artifact.artifact_id, "schema_version": SCHEMA_SPLIT_SUMMARY},
        )
        artifacts.append(split_report_artifact)

        return NodeOutput(
            artifacts=artifacts,
            metrics={"train_count": role_map["train"].height, "test_count": role_map["test"].height, "oot_count": role_map["oot"].height})

    def _stratified_split(self, df: pl.DataFrame, target_column: str, train_frac: float, test_frac: float, oot_frac: float, seed: int) -> dict[str, pl.DataFrame]:
        rng = np.random.default_rng(seed)
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
        return {"train": df[train_indices], "test": df[test_indices], "oot": df[oot_indices]}
