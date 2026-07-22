from __future__ import annotations

from typing import Any

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA, SCHEMA_SAMPLE_DEFINITION
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


class DefineModellingMetadataNode(NodeType):
    node_type = "cardre.define_modelling_metadata"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train"]
    output_roles: list[str] = ["definition"]

    __definition__ = NodeDefinition(
        node_type="cardre.define_modelling_metadata",
        version="1",
        category="transform",
        description="Define modelling metadata including target specification",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=("dataset",)),)),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("definition", required=True, kinds=("definition",)),)),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    VALID_REJECT_INFERENCE_POSITIONS = {
        "not_applied",
        "excluded",
        "ignored",
        "documented_method",
    }

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        reject_inference_position = params.get("reject_inference_position")
        if reject_inference_position is None:
            return errors
        if not isinstance(reject_inference_position, str) or not reject_inference_position:
            errors.append("reject_inference_position must be a non-empty string when provided")
            return errors
        if reject_inference_position not in self.VALID_REJECT_INFERENCE_POSITIONS:
            errors.append(
                "reject_inference_position must be one of "
                f"{sorted(self.VALID_REJECT_INFERENCE_POSITIONS)}, got {reject_inference_position!r}"
            )
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        dataset_artifact = context.inputs.first("input") or context.inputs.first("train")
        df = context.inputs.read_dataframe(dataset_artifact)

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
            "purpose": params.get("purpose", ""),
            "population": params.get("population", ""),
            "product": params.get("product", ""),
            "segment": params.get("segment", ""),
            "observation_window": params.get("observation_window"),
            "performance_window": params.get("performance_window"),
            "reject_inference_position": params.get("reject_inference_position", ""),
        }

        metadata["schema_version"] = SCHEMA_MODELLING_METADATA
        context.outputs.publish_json(
            role="definition",
            kind=EvidenceKind.MODELLING_METADATA,
            payload=metadata,
            metadata={"source_artifact_id": getattr(dataset_artifact, "artifact_id", ""), "schema_version": SCHEMA_MODELLING_METADATA},
        )

        context.outputs.add_metric("target_column", target_column)
        return context.outputs.build_result()


class DevelopmentSampleDefinitionNode(NodeType):
    node_type = "cardre.development_sample_definition"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "train", "definition"]
    output_roles: list[str] = ["definition"]

    __definition__ = NodeDefinition(
        node_type="cardre.development_sample_definition",
        version="1",
        category="transform",
        description="Define development sample population and weighting",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=("dataset",)), ArtifactRoleSpec("train", required=False, kinds=("dataset",)), ArtifactRoleSpec("definition", required=False, kinds=("definition",)))),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("definition", required=True, kinds=("definition",)),)),
        parameter_schema=None,
        optional_dependencies=(),
        tier="launch",
    )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        domain = params.get("sample_domain", "ttd")
        if domain not in ("ttd", "otb"):
            errors.append("sample_domain must be 'ttd' or 'otb'")
        if domain == "ttd":
            rejection_source = params.get("rejection_source")
            if rejection_source is not None and rejection_source not in ("flag_column", "target_missing"):
                errors.append("rejection_source must be 'flag_column', 'target_missing', or None")
        if domain == "otb" and not params.get("approval_column"):
            errors.append("approval_column is required for otb sample domain")
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params

        sample_domain = params.get("sample_domain", "ttd")
        rejection_source = params.get("rejection_source")
        rejection_column = params.get("rejection_column")
        rejection_values = params.get("rejection_values")
        approval_column = params.get("approval_column")
        approval_values = params.get("approval_values", [])
        weight_column = params.get("weight_column")

        dataset_artifact = context.inputs.first("input") or context.inputs.first("train")
        df = context.inputs.read_dataframe(dataset_artifact)
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

        context.outputs.publish_json(
            role="definition",
            kind=EvidenceKind.SAMPLE_DEFINITION,
            payload=sample_def,
            metadata={"schema_version": SCHEMA_SAMPLE_DEFINITION},
        )

        context.outputs.add_metric("sample_method", sample_def["sample_method"])
        return context.outputs.build_result()
