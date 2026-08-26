from __future__ import annotations

from typing import Any

from cardre.domain.evidence.kinds import EvidenceKind, RoleKind
from cardre.domain.evidence.schemas import SCHEMA_MODELLING_METADATA, SCHEMA_SAMPLE_DEFINITION
from cardre.domain.plans.target_definition import validate_target_definition
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

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Define Modelling Metadata",
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
                            required=True,
                            help_text="Name of the column containing the binary target",
                        ),
                        ParameterDefinition(
                            name="good_values",
                            label="Good Values",
                            kind="list",
                            default=["good"],
                            required=True,
                            help_text="Values of the target column that map to the good (non-event) class",
                        ),
                        ParameterDefinition(
                            name="bad_values",
                            label="Bad Values",
                            kind="list",
                            default=["bad"],
                            required=True,
                            help_text="Values of the target column that map to the bad (event) class",
                        ),
                        ParameterDefinition(
                            name="indeterminate_values",
                            label="Indeterminate Values",
                            kind="list",
                            default=[],
                            required=False,
                            help_text="Values of the target column that are neither good nor bad",
                        ),
                        ParameterDefinition(
                            name="purpose",
                            label="Purpose",
                            kind="string",
                            default="application_credit_scorecard",
                            help_text="Purpose of the scorecard model",
                        ),
                        ParameterDefinition(
                            name="population",
                            label="Population",
                            kind="string",
                            default="",
                            help_text="Description of the modelled population",
                        ),
                        ParameterDefinition(
                            name="product",
                            label="Product",
                            kind="string",
                            default="",
                            help_text="Product the scorecard applies to",
                        ),
                        ParameterDefinition(
                            name="segment",
                            label="Segment",
                            kind="string",
                            default="",
                            help_text="Segment the scorecard applies to",
                        ),
                        ParameterDefinition(
                            name="observation_window",
                            label="Observation Window",
                            kind="string",
                            default="",
                            help_text="Observation window over which predictors are measured",
                        ),
                        ParameterDefinition(
                            name="performance_window",
                            label="Performance Window",
                            kind="string",
                            default="",
                            help_text="Performance window over which the outcome is observed",
                        ),
                        ParameterDefinition(
                            name="reject_inference_position",
                            label="Reject Inference Position",
                            kind="string",
                            default="not_applied",
                            required=False,
                            constraint=ParameterConstraint(
                                enum_values=[""] + sorted(cls.VALID_REJECT_INFERENCE_POSITIONS),
                            ),
                            help_text="Where reject inference is applied in the modelling process",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        # Always run the target-definition checks: they must not be skipped
        # when reject_inference_position is absent or malformed.
        errors: list[str] = validate_target_definition(params)

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
        good_values = list(params.get("good_values") or [])
        bad_values = list(params.get("bad_values") or [])
        # Defensive: an explicit null would otherwise crash the set
        # comprehension below. Validated params never carry null, but legacy
        # persisted state may.
        indeterminate_values = list(params.get("indeterminate_values") or [])

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

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Development Sample Definition",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="sample_method",
                            label="Sample Method",
                            kind="string",
                            default="full_population",
                            required=True,
                            constraint=ParameterConstraint(enum_values=["full_population"]),
                            help_text="Method used to select the development sample",
                        ),
                        ParameterDefinition(
                            name="sample_domain",
                            label="Sample Domain",
                            kind="string",
                            default="ttd",
                            required=True,
                            constraint=ParameterConstraint(enum_values=["ttd"]),
                            help_text="Domain the development sample is drawn from",
                        ),
                        ParameterDefinition(
                            name="sample_description",
                            label="Sample Description",
                            kind="string",
                            default="",
                            required=False,
                            help_text="Free-text description of the development sample",
                        ),
                        ParameterDefinition(
                            name="weight_column",
                            label="Weight Column",
                            kind="string",
                            default=None,
                            required=False,
                            help_text="Optional numeric column used to weight rows in the sample",
                        ),
                        ParameterDefinition(
                            name="population_bad_rate",
                            label="Population Bad Rate",
                            kind="float",
                            default=None,
                            required=False,
                            constraint=ParameterConstraint(min_value=0.0, max_value=1.0),
                            help_text="Expected bad rate of the population (null = unknown)",
                        ),
                        ParameterDefinition(
                            name="prior_probability_adjustment",
                            label="Prior Probability Adjustment",
                            kind="object",
                            default=None,
                            required=False,
                            help_text="Optional prior-probability adjustment configuration",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        domain = params.get("sample_domain", "ttd")
        if domain not in ("ttd",):
            errors.append("sample_domain must be 'ttd'")
        sample_method = params.get("sample_method", "full_population")
        if sample_method not in ("full_population",):
            errors.append("sample_method must be 'full_population'")
        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params

        sample_domain = params.get("sample_domain", "ttd")
        sample_method = params.get("sample_method", "full_population")
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
            "sample_method": sample_method,
            "weight_column": weight_column,
            "population_bad_rate": params.get("population_bad_rate"),
            "prior_probability_adjustment": params.get("prior_probability_adjustment"),
            "sample_domain": sample_domain,
            "total_rows": total_rows,
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
