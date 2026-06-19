from __future__ import annotations

import json
from typing import Any

from cardre.artifacts import write_json_artifact
from cardre.audit import ExecutionContext, NodeOutput, NodeType, json_logical_hash
from cardre.evidence import (
    ArtifactEvidenceReader,
    EvidenceKind,
    SCHEMA_BIN_DEFINITION,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_MODELLING_METADATA,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_WOE_TABLE,
)


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

        scorecard_art = next(
            a for a in context.input_artifacts
            if a.role == "scorecard"
            and a.metadata.get("schema_version") == SCHEMA_SCORE_SCALING
        )
        scorecard = json.loads(store.artifact_path(scorecard_art).read_text())

        def _find_by_schema(artifacts, schema_version):
            matches = [
                a
                for a in artifacts
                if a.metadata.get("schema_version") == schema_version
            ]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise ValueError(
                    f"Missing artifact with schema_version={schema_version}"
                )
            raise ValueError(
                f"Multiple artifacts with schema_version={schema_version}"
            )

        bin_def_art = _find_by_schema(
            context.input_artifacts, SCHEMA_BIN_DEFINITION
        )
        woe_table_art = _find_by_schema(
            context.input_artifacts, SCHEMA_WOE_TABLE
        )
        model_art = _find_by_schema(
            context.input_artifacts, SCHEMA_MODEL_ARTIFACT
        )
        model_raw = json.loads(store.artifact_path(model_art).read_text())

        selection_art = next(
            (
                a
                for a in context.input_artifacts
                if a.metadata.get("schema_version")
                == SCHEMA_SELECTION_DEFINITION
            ),
            None,
        )

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
        if selection_art is not None:
            components["selection_logical_hash"] = selection_art.logical_hash
            components["selection_physical_hash"] = selection_art.physical_hash

        model_features = model.features
        raw_fc = model_raw.get("feature_contract", {})
        transformation_strategy = raw_fc.get("transformation_strategy", "woe")
        order_hash = raw_fc.get(
            "order_hash", json_logical_hash({"features": model_features})
        )

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

        score_scaling = {
            "base_score": scorecard.get("base_score", 600),
            "base_odds": scorecard.get("base_odds", 50.0),
            "points_to_double_odds": scorecard.get(
                "points_to_double_odds", 20.0
            ),
            "higher_score_is_lower_risk": scorecard.get(
                "higher_score_is_lower_risk", True
            ),
            "factor": scorecard.get("factor", 0.0),
            "offset": scorecard.get("offset", 0.0),
            "intercept": scorecard.get("intercept", 0.0),
            "base_points": scorecard.get("base_points", 0.0),
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
        scorecard_intercept = scorecard.get("intercept")
        if scorecard_intercept is not None and abs(
            float(scorecard_intercept) - float(model_intercept)
        ) > 1e-6:
            raise ValueError(
                f"Frozen scorecard bundle cannot be created: scorecard intercept "
                f"({scorecard_intercept}) differs from model intercept ({model_intercept})"
            )

        model_target = model.target_column
        scorecard_target = str(scorecard.get("target_column", ""))
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
