from __future__ import annotations

from typing import Any

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.domain.evidence.schemas import (
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_SELECTION_DEFINITION,
)
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)


class FrozenScorecardBundleNode(NodeType):
    node_type = "cardre.freeze_scorecard_bundle"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["definition", "report", "model", "scorecard"]
    output_roles: list[str] = ["scorecard"]

    __definition__ = NodeDefinition(
        node_type="cardre.freeze_scorecard_bundle",
        version="1",
        category="fit",
        description="Freeze a scorecard bundle for deployment",
        input_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("definition", kinds=(EvidenceKind.BIN_DEFINITION, EvidenceKind.SELECTION_DEFINITION)),
                ArtifactRoleSpec("report"),
                ArtifactRoleSpec("model", kinds=(EvidenceKind.MODEL_ARTIFACT,)),
                ArtifactRoleSpec("scorecard", kinds=(EvidenceKind.SCORE_SCALING,)),
            ),
        ),
        output_contract=ArtifactContract(
            roles=(
                ArtifactRoleSpec("scorecard", kinds=(EvidenceKind.FROZEN_SCORECARD_BUNDLE,)),
            ),
        ),
        parameter_schema=None,
    )

    def run(self, context: NodeContext) -> NodeResult:

        meta_list = context.inputs.by_kind(EvidenceKind.MODELLING_METADATA)
        meta = meta_list[0] if meta_list else None
        if meta is None:
            raise ValueError("No modelling metadata found")

        bin_list = context.inputs.by_kind(EvidenceKind.BIN_DEFINITION)
        if not bin_list:
            raise ValueError("No bin definition found")
        bin_def = bin_list[0]

        woe_list = context.inputs.by_kind(EvidenceKind.WOE_TABLE)
        if not woe_list:
            raise ValueError("No WOE table found")
        woe_table = woe_list[0]

        model_list = context.inputs.by_kind(EvidenceKind.MODEL_ARTIFACT)
        if not model_list:
            raise ValueError("No model artifact found")
        model = model_list[0]

        scorecard_list = context.inputs.by_kind(EvidenceKind.SCORE_SCALING)
        if not scorecard_list:
            raise ValueError("No score scaling found")
        scorecard = scorecard_list[0]

        definition_arts = context.inputs.by_role("definition")
        selection_candidates = [
            a for a in definition_arts
            if a.metadata.get("schema_version") == SCHEMA_SELECTION_DEFINITION
        ]
        if len(selection_candidates) > 1:
            raise ValueError(
                "Frozen scorecard bundle cannot be created: multiple selection definition artifacts found"
            )
        selection_art = selection_candidates[0] if selection_candidates else None
        selection_def = (
            context.inputs.read(selection_art, EvidenceKind.SELECTION_DEFINITION)
            if selection_art is not None
            else None
        )

        scorecard_art = context.inputs.artifact_ref(scorecard.source_artifact_id)
        model_art = context.inputs.artifact_ref(model.source_artifact_id)
        bin_def_art = context.inputs.artifact_ref(bin_def.source_artifact_id)
        woe_table_art = context.inputs.artifact_ref(woe_table.source_artifact_id)
        selection_art_ref = context.inputs.artifact_ref(selection_def.source_artifact_id) if selection_def is not None else None
        if scorecard_art is None or model_art is None or bin_def_art is None or woe_table_art is None:
            raise ValueError("Frozen scorecard bundle cannot be created: missing source artifact reference")

        created_from = {
            "run_id": context.runtime.run_id,
            "plan_version_id": context.runtime.plan_version_id,
            "step_id": context.runtime.step_id,
            "canonical_step_id": context.step_spec.canonical_step_id,
            "branch_id": context.step_spec.branch_id or "",
        }

        target = {
            "target_column": meta.target_column,
            "good_values": [str(v) for v in meta.good_values],
            "bad_values": [str(v) for v in meta.bad_values],
            "event_convention": "bad",
        }

        components = {
            "bin_definition_logical_hash": bin_def_art.logical_hash,
            "bin_definition_physical_hash": bin_def_art.physical_hash,
            "woe_table_logical_hash": woe_table_art.logical_hash,
            "woe_table_physical_hash": woe_table_art.physical_hash,
            "model_logical_hash": model_art.logical_hash,
            "model_physical_hash": model_art.physical_hash,
            "scorecard_logical_hash": scorecard_art.logical_hash,
            "scorecard_physical_hash": scorecard_art.physical_hash,
        }
        if selection_def is not None and selection_art_ref is not None:
            components["selection_logical_hash"] = selection_art_ref.logical_hash
            components["selection_physical_hash"] = selection_art_ref.physical_hash

        model_features = model.features
        raw_fc = model.feature_contract
        transformation_strategy = raw_fc.transformation_strategy or "woe"
        order_hash = raw_fc.order_hash or json_logical_hash({"features": model_features})

        source_variables = model.source_variables
        if source_variables is None:
            if model_features and all(
                f.endswith("_woe") for f in model_features
            ):
                source_variables = [f[:-4] for f in model_features]
            else:
                source_variables = list(model_features)

        feature_contract = {
            "features": model_features,
            "source_variables": source_variables,
            "transformation_strategy": transformation_strategy,
            "order_hash": order_hash,
            "missing_policy": raw_fc.missing_policy or "error",
            "unknown_category_policy": raw_fc.unknown_category_policy or "error",
        }

        base_odds = scorecard.base_odds
        higher_is_lower_risk = scorecard.higher_score_is_lower_risk
        intercept = scorecard.intercept
        base_points = scorecard.base_points
        if base_points is None:
            direction = -1.0 if higher_is_lower_risk else 1.0
            base_points = round(float(scorecard.offset) + direction * float(scorecard.factor) * intercept, 2)

        score_scaling = {
            "base_score": scorecard.base_score,
            "base_odds": base_odds,
            "points_to_double_odds": scorecard.points_to_double_odds,
            "score_direction": "higher_is_lower_risk" if higher_is_lower_risk else "higher_is_better",
            "factor": scorecard.factor,
            "offset": scorecard.offset,
            "intercept": intercept,
            "base_points": base_points,
        }

        woe_mapped_vars = set(woe_table.mapping.keys())
        for var in source_variables:
            if var not in woe_mapped_vars:
                raise ValueError(
                    f"Frozen scorecard bundle cannot be created: source variable "
                    f"'{var}' used by model but not found in WOE mapping"
                )

        expected_order_hash = json_logical_hash(
            {"features": model_features}
        )
        if order_hash != expected_order_hash:
            raise ValueError(
                f"Frozen scorecard bundle cannot be created: feature order hash "
                f"({order_hash}) does not match computed hash ({expected_order_hash})"
            )

        model_intercept = model.intercept
        if scorecard.has_explicit_intercept:
            scorecard_intercept = scorecard.intercept
            if abs(float(scorecard_intercept) - float(model_intercept)) > 1e-6:
                raise ValueError(
                    f"Frozen scorecard bundle cannot be created: scorecard intercept "
                    f"({scorecard_intercept}) differs from model intercept ({model_intercept})"
                )

        model_target = model.target_column
        scorecard_target = scorecard.target_column
        if model_target and scorecard_target and model_target != scorecard_target:
            raise ValueError(
                f"Frozen scorecard bundle cannot be created: model target "
                f"({model_target}) differs from scorecard target ({scorecard_target})"
            )
        if (
            meta.target_column
            and model_target
            and meta.target_column != model_target
        ):
            raise ValueError(
                f"Frozen scorecard bundle cannot be created: modelling metadata target "
                f"({meta.target_column}) differs from model target ({model_target})"
            )

        bundle = {
            "schema_version": SCHEMA_FROZEN_SCORECARD_BUNDLE,
            "bundle_type": "scorecard_application",
            "created_from": created_from,
            "target": target,
            "components": components,
            "feature_contract": feature_contract,
            "score_scaling": score_scaling,
            "warnings": [],
        }

        sidecar_metadata: dict[str, Any] = {
            "schema_version": SCHEMA_FROZEN_SCORECARD_BUNDLE,
            "model_artifact_id": model_art.artifact_id,
            "scorecard_artifact_id": scorecard_art.artifact_id,
            "bin_definition_artifact_id": bin_def_art.artifact_id,
            "woe_table_artifact_id": woe_table_art.artifact_id,
            "feature_count": len(model_features),
        }
        if selection_art_ref is not None:
            sidecar_metadata["selection_artifact_id"] = (
                selection_art_ref.artifact_id
            )

        context.outputs.publish_json(
            role="scorecard",
            kind=EvidenceKind.FROZEN_SCORECARD_BUNDLE,
            payload=bundle,
            metadata=sidecar_metadata,
        )

        context.outputs.add_metric("feature_count", len(model_features))
        return context.outputs.build_result()
