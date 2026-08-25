from __future__ import annotations

import numpy as np
import polars as pl

from cardre.domain.evidence.kinds import EvidenceKind, RoleKind
from cardre.domain.evidence.schemas import SCHEMA_SPLIT_SUMMARY
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


class ValidateBinaryTargetNode(NodeType):
    node_type = "cardre.validate_binary_target"
    version = "1"
    category = "transform"

    __definition__ = NodeDefinition(
        node_type="cardre.validate_binary_target",
        version="1",
        category="transform",
        description="Validate binary target column constraints",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=(RoleKind.DATASET,)),)),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("report", required=True, kinds=(EvidenceKind.SPLIT_SUMMARY,), media_types=("application/json",), schema_versions=(SCHEMA_SPLIT_SUMMARY,)),)),
    )

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

    def run(self, context: NodeContext) -> NodeResult:
        input_artifact = context.inputs.first("input") or context.inputs.first("train")
        params = context.params
        target_col = params.get("target_column", "credit_risk_class")
        df = context.inputs.read_dataframe(input_artifact)
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

        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.SPLIT_SUMMARY,
            payload=report,
            metadata={"source_artifact_id": getattr(input_artifact, "artifact_id", ""), "schema_version": SCHEMA_SPLIT_SUMMARY},
        )

        context.outputs.add_metric("is_binary", report["is_binary"])
        return context.outputs.build_result()


class SplitTrainTestOotNode(NodeType):
    node_type = "cardre.split_train_test_oot"
    version = "2"
    category = "transform"

    __definition__ = NodeDefinition(
        node_type="cardre.split_train_test_oot",
        version="2",
        category="transform",
        description="Split dataset into train/test/oot partitions",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=(RoleKind.DATASET,)), ArtifactRoleSpec("definition", required=False, kinds=(RoleKind.DEFINITION,)))),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("train", required=True, kinds=(EvidenceKind.MODELLING_METADATA,), media_types=("application/vnd.apache.parquet",), schema_versions=()), ArtifactRoleSpec("test", required=True, kinds=(EvidenceKind.MODELLING_METADATA,), media_types=("application/vnd.apache.parquet",), schema_versions=()), ArtifactRoleSpec("oot", required=True, kinds=(EvidenceKind.MODELLING_METADATA,), media_types=("application/vnd.apache.parquet",), schema_versions=()), ArtifactRoleSpec("report", required=True, kinds=(EvidenceKind.SPLIT_SUMMARY,), media_types=("application/json",), schema_versions=(SCHEMA_SPLIT_SUMMARY,)))),
    )

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
            ],
        )

    def run(self, context: NodeContext) -> NodeResult:
        dataset_artifact = context.inputs.first("input")
        params = context.params
        method = params.get("method", "random_stratified")
        train_frac = float(params.get("train_fraction", 0.6))
        test_frac = float(params.get("test_fraction", 0.2))
        oot_frac = float(params.get("oot_fraction", 0.2))
        seed = int(params.get("random_seed", 42))
        target_column = params.get("target_column", "credit_risk_class")
        total = train_frac + test_frac + oot_frac
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Split fractions sum to {total}, expected 1.0")

        df = context.inputs.read_dataframe(dataset_artifact)

        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' not found in dataset")
        role_map = self._stratified_split(df, target_column, train_frac, test_frac, oot_frac, seed)

        for role in ("train", "test", "oot"):
            subset = role_map[role]
            context.outputs.publish_table(
                role=role,
                kind=EvidenceKind.MODELLING_METADATA,
                frame=subset,
                metadata={"source_artifact_id": getattr(dataset_artifact, "artifact_id", ""), "method": method, "row_count": subset.height},
            )

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
            "random_seed": seed,
            "fractions": {"train": train_frac, "test": test_frac, "oot": oot_frac},
            "row_counts": {role: subset.height for role, subset in role_map.items()},
            "target_rates": target_rates, "warnings": split_warnings,
            "source_artifact_id": getattr(dataset_artifact, "artifact_id", ""),
        }
        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.SPLIT_SUMMARY,
            payload=split_report,
            metadata={"source_artifact_id": getattr(dataset_artifact, "artifact_id", ""), "schema_version": SCHEMA_SPLIT_SUMMARY},
        )
        for w in split_warnings:
            context.outputs.add_warning(w)
        context.outputs.add_metric("train_count", role_map["train"].height)
        context.outputs.add_metric("test_count", role_map["test"].height)
        context.outputs.add_metric("oot_count", role_map["oot"].height)
        return context.outputs.build_result()

    def _stratified_split(self, df: pl.DataFrame, target_column: str, train_frac: float, test_frac: float, oot_frac: float, seed: int) -> dict[str, pl.DataFrame]:
        rng = np.random.default_rng(seed)
        df_with_idx = df.with_columns(pl.Series("__row_idx__", range(df.height)))
        groups = df_with_idx.group_by(target_column).agg(pl.col("__row_idx__"))
        # Iterate groups in deterministic order: polars group_by iteration
        # order is not guaranteed, and the RNG is consumed per group, so a
        # varying group order would make the split non-reproducible.
        group_rows = sorted(groups.iter_rows(), key=lambda row: str(row[0]))
        train_indices: list[int] = []
        test_indices: list[int] = []
        oot_indices: list[int] = []
        for row in group_rows:
            group_indices = list(row[1])
            rng.shuffle(group_indices)
            n = len(group_indices)
            n_train = max(1, int(n * train_frac))
            n_test = max(1, int(n * test_frac))
            train_indices.extend(group_indices[:n_train])
            test_indices.extend(group_indices[n_train:n_train + n_test])
            oot_indices.extend(group_indices[n_train + n_test:])
        return {"train": df[train_indices], "test": df[test_indices], "oot": df[oot_indices]}
