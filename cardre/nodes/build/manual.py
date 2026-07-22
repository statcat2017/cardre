from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.artifacts import write_json_artifact
from cardre.engine.binning.definition import SCHEMA_BIN_DEFINITION
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType
from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterDefinition,
)


class ManualBinningNode(NodeType):
    node_type = "cardre.manual_binning"
    version = "1"
    category = "refinement"
    input_roles: list[str] = ["definition"]
    output_roles: list[str] = ["definition"]

    VALID_ACTIONS = {
        "merge_bins", "group_categories",
        "reject_variable", "reorder_missing_bin", "reorder_special_bin",
    }

    REASON_CODES = frozenset({
        "business_interpretability", "monotonicity", "sparse_bin",
        "zero_cell", "missing_value_treatment", "special_value_treatment",
        "regulatory_or_policy", "other",
    })

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Manual Binning",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Apply manual binning overrides (merge, group, reject, reorder).",
                    params=[
                        ParameterDefinition(
                            name="overrides",
                            label="Overrides",
                            kind="list",
                            default=[],
                            help_text=(
                                "List of override objects. Each object requires: "
                                "variable (str), action (one of merge_bins, group_categories, "
                                "reject_variable, reorder_missing_bin, reorder_special_bin), "
                                "reason (str), source_bin_ids (list[str]), "
                                "and optionally new_label (str), reason_code (str) from: "
                                + ", ".join(sorted(ManualBinningNode.REASON_CODES)) + "."
                            ),
                        ),
                        ParameterDefinition(
                            name="reviewed",
                            label="Bin review complete",
                            kind="bool",
                            default=False,
                            help_text="Set to true when manual bin review is complete.",
                        ),
                        ParameterDefinition(
                            name="accept_automated",
                            label="Accept automated bins",
                            kind="bool",
                            default=False,
                            help_text="Set to true to accept automated bins without manual overrides (discards any overrides).",
                        ),
                    ],
                ),
            ],
            default_method="default",
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for i, override in enumerate(list(params.get("overrides", []))):
            prefix = f"overrides[{i}]"
            if not isinstance(override, dict):
                errors.append(f"{prefix} must be a dict")
                continue
            variable = override.get("variable", "")
            action = override.get("action", "")
            reason = override.get("reason", "")
            reason_code = override.get("reason_code")
            if not reason:
                errors.append(f"{prefix}: override for '{variable}' requires a non-empty reason")
            if reason_code is not None and reason_code not in self.REASON_CODES:
                errors.append(f"{prefix}: unknown reason_code '{reason_code}'")
            if action not in self.VALID_ACTIONS:
                errors.append(f"{prefix}: unsupported action '{action}'")
            source_bin_ids = override.get("source_bin_ids", [])
            if not isinstance(source_bin_ids, list):
                errors.append(f"{prefix}: source_bin_ids must be a list")
            if action == "merge_bins" and len(source_bin_ids) < 2:
                errors.append(f"{prefix}: merge_bins requires at least 2 source bins")
        if params.get("reviewed") and params.get("accept_automated"):
            errors.append("reviewed and accept_automated cannot both be true.")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        overrides = params.get("overrides", [])
        reader = ArtifactEvidenceReader(store)

        bin_def_obj = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        sel_def = reader.find_optional(context.input_artifacts, EvidenceKind.SELECTION_DEFINITION)

        bin_def = bin_def_obj.to_dict()

        selected_vars: set[str] = set()
        if sel_def is not None:
            selected_vars = sel_def.selected_names

        errors = validate_manual_binning_overrides(bin_def, overrides, selected_vars if sel_def else None)
        if errors:
            raise ValueError("; ".join(errors))

        refined = apply_manual_binning_overrides(bin_def, overrides, selected_vars if sel_def else None)

        refined["schema_version"] = SCHEMA_BIN_DEFINITION
        artifact = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"manual-binning-{context.step_spec.step_id}",
            payload=refined,
            metadata={"override_count": len(overrides), "schema_version": SCHEMA_BIN_DEFINITION},
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"override_count": len(overrides)})


def validate_manual_binning_overrides(
    bin_def: dict[str, Any], overrides: list[dict[str, Any]], selected_vars: set[str] | None = None
) -> list[str]:
    from cardre.engine.binning.definition import LifecycleBinDefinition
    typed = LifecycleBinDefinition.from_payload(bin_def)
    return LifecycleBinDefinition.validate_overrides(typed, overrides, selected_vars)


def apply_manual_binning_overrides(
    bin_def: dict[str, Any], overrides: list[dict[str, Any]], selected_vars: set[str] | None = None
) -> dict[str, Any]:
    from cardre.engine.binning.definition import LifecycleBinDefinition
    typed = LifecycleBinDefinition.from_payload(bin_def)
    result = LifecycleBinDefinition.apply_overrides(typed, overrides, selected_vars)
    return result.to_payload()
