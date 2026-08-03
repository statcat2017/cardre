from __future__ import annotations

from typing import Any

from cardre.domain.evidence.kinds import EvidenceKind, RoleKind
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA, SCHEMA_SAMPLE_DEFINITION
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


def _normalize_target_values(values: Any) -> list[str]:
    """Return the exact string representation of each non-blank, non-null
    member, preserving order (duplicates collapse via the caller's set)."""
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if v is not None and str(v).strip()]


def _target_list_errors(params: dict[str, Any], key: str) -> list[str]:
    """Reject null or blank members in a target value list.

    Execution consumes each member verbatim (``str(v)`` without stripping),
    so a blank or null member would become a spurious declared category.
    """
    errors: list[str] = []
    values = params.get(key)
    if values is None:
        return errors
    if not isinstance(values, list):
        return [f"{key} must be a list"]
    for i, value in enumerate(values):
        if value is None:
            errors.append(f"{key}[{i}] must not be null")
        elif isinstance(value, str) and not value.strip():
            errors.append(f"{key}[{i}] must not be blank")
    return errors


def _validate_target_definition(params: dict[str, Any]) -> list[str]:
    """Data-independent validation of the target definition.

    These checks do not require the dataset: they validate the shape of the
    declared target, good, bad and indeterminate value sets so a semantically
    contradictory definition cannot be committed as immutable. Overlap checks
    use the exact representation execution consumes (``str(v)`` verbatim),
    and blank/null members are rejected outright.
    """
    errors: list[str] = []

    target_column = params.get("target_column")
    if not isinstance(target_column, str) or not target_column.strip():
        errors.append("target_column must be non-whitespace text")

    for key in ("good_values", "bad_values", "indeterminate_values"):
        errors.extend(_target_list_errors(params, key))

    good_values = _normalize_target_values(params.get("good_values"))
    bad_values = _normalize_target_values(params.get("bad_values"))
    indeterminate_values = _normalize_target_values(params.get("indeterminate_values"))

    if not good_values:
        errors.append("good_values must contain at least one non-blank value")
    if not bad_values:
        errors.append("bad_values must contain at least one non-blank value")

    good_set = set(good_values)
    bad_set = set(bad_values)
    indeterminate_set = set(indeterminate_values)

    overlap_gb = good_set & bad_set
    if overlap_gb:
        errors.append(f"good_values and bad_values must be disjoint; overlap: {sorted(overlap_gb)}")
    overlap_gi = good_set & indeterminate_set
    if overlap_gi:
        errors.append(
            f"good_values and indeterminate_values must be disjoint; overlap: {sorted(overlap_gi)}"
        )
    overlap_bi = bad_set & indeterminate_set
    if overlap_bi:
        errors.append(
            f"bad_values and indeterminate_values must be disjoint; overlap: {sorted(overlap_bi)}"
        )

    return errors


class DefineModellingMetadataNode(NodeType):
    node_type = "cardre.define_modelling_metadata"
    version = "1"
    category = "transform"

    __definition__ = NodeDefinition(
        node_type="cardre.define_modelling_metadata",
        version="1",
        category="transform",
        description="Define modelling metadata including target specification",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=(RoleKind.DATASET,)),)),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("definition", required=True, kinds=(EvidenceKind.MODELLING_METADATA, EvidenceKind.SAMPLE_DEFINITION), media_types=("application/json",), schema_versions=(SCHEMA_MODELLING_METADATA, SCHEMA_SAMPLE_DEFINITION)),)),
    )

    VALID_REJECT_INFERENCE_POSITIONS = {
        "not_applied",
        "excluded",
        "ignored",
        "documented_method",
    }

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        # Always run the target-definition checks: they must not be skipped
        # when reject_inference_position is absent or malformed.
        errors: list[str] = _validate_target_definition(params)

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

    __definition__ = NodeDefinition(
        node_type="cardre.development_sample_definition",
        version="1",
        category="transform",
        description="Define development sample population and weighting",
        input_contract=ArtifactContract(roles=(ArtifactRoleSpec("input", required=True, kinds=(RoleKind.DATASET,)), ArtifactRoleSpec("train", required=False, kinds=(RoleKind.DATASET,)), ArtifactRoleSpec("definition", required=False, kinds=(RoleKind.DEFINITION,)))),
        output_contract=ArtifactContract(roles=(ArtifactRoleSpec("definition", required=True, kinds=(EvidenceKind.MODELLING_METADATA, EvidenceKind.SAMPLE_DEFINITION), media_types=("application/json",), schema_versions=(SCHEMA_MODELLING_METADATA, SCHEMA_SAMPLE_DEFINITION)),)),
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
