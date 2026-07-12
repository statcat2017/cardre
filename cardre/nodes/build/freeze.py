from __future__ import annotations

import json  # noqa: F401 — imported for monkeypatch compatibility in tests
from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import SCHEMA_FROZEN_SCORECARD_BUNDLE, SCHEMA_SELECTION_DEFINITION
from cardre.artifacts import write_json_artifact
from cardre.domain.artifacts import json_logical_hash
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType


class FrozenScorecardBundleNode(NodeType):
    node_type = "cardre.freeze_scorecard_bundle"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["definition", "report", "model", "scorecard"]
    output_roles: list[str] = ["scorecard"]

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)

        meta = reader.find(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        bin_def = reader.find(context.input_artifacts, EvidenceKind.BIN_DEFINITION)
        woe_table = reader.find(context.input_artifacts, EvidenceKind.WOE_TABLE)
        model = reader.find(context.input_artifacts, EvidenceKind.MODEL_ARTIFACT)
        scorecard = reader.find(context.input_artifacts, EvidenceKind.SCORE_SCALING)
        selection_candidates = [
            a
            for a in context.input_artifacts
            if a.metadata.get("schema_version") == SCHEMA_SELECTION_DEFINITION
        ]
        if len(selection_candidates) > 1:
            raise ValueError(
                "Frozen scorecard bundle cannot be created: multiple selection definition artifacts found"
            )
        selection_art = selection_candidates[0] if selection_candidates else None
        selection_def = (
            reader.read_optional(selection_art.artifact_id, EvidenceKind.SELECTION_DEFINITION)
            if selection_art is not None
            else None
        )

        scorecard_art = store.get_artifact(scorecard.source_artifact_id)
        model_art = store.get_artifact(model.source_artifact_id)
        bin_def_art = store.get_artifact(bin_def.source_artifact_id)
        woe_table_art = store.get_artifact(woe_table.source_artifact_id)
        selection_art = store.get_artifact(selection_def.source_artifact_id) if selection_def is not None else None
        if scorecard_art is None or model_art is None or bin_def_art is None or woe_table_art is None:
            raise ValueError("Frozen scorecard bundle cannot be created: missing source artifact reference")

        created_from = {
            "run_id": context.run_id,
            "plan_version_id": context.plan_version_id,
            "step_id": context.step_spec.step_id,
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
        if selection_def is not None and selection_art is not None:
            components["selection_logical_hash"] = selection_art.logical_hash
            components["selection_physical_hash"] = selection_art.physical_hash

        model_features = model.features
        raw_fc = model.feature_contract
        transformation_strategy = raw_fc.get("transformation_strategy", "woe")
        order_hash = raw_fc.get(
            "order_hash", json_logical_hash({"features": model_features})
        )

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
            "missing_policy": raw_fc.get("missing_policy", "error"),
            "unknown_category_policy": raw_fc.get(
                "unknown_category_policy", "error"
            ),
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
            "points_to_double_odds": scorecard.pdo,
            "higher_score_is_lower_risk": higher_is_lower_risk,
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
        if selection_art is not None:
            sidecar_metadata["selection_artifact_id"] = (
                selection_art.artifact_id
            )

        artifact = write_json_artifact(
            store,
            artifact_type="scorecard",
            role="scorecard",
            stem=f"frozen-scorecard-bundle-{context.step_spec.step_id}",
            payload=bundle,
            metadata=sidecar_metadata,
        )

        return NodeOutput(
            artifacts=[artifact],
            metrics={"feature_count": len(model_features)},
        )
