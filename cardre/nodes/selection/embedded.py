from __future__ import annotations

import logging
from typing import Any

from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes._training_utils import prepare_supervised_training_data
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)
from cardre.nodes.selection._definition import merge_selection_definition

logger = logging.getLogger(__name__)


class FeatureSelectionEmbeddedNode(NodeType):
    node_type = "cardre.feature_selection_embedded"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition", "report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        importance_threshold = params.get("importance_threshold", 0.0)
        try:
            if float(importance_threshold) < 0:
                errors.append("importance_threshold must be >= 0")
        except (ValueError, TypeError):
            errors.append("importance_threshold must be a number")

        max_features = params.get("max_features")
        if max_features is not None:
            try:
                if int(max_features) < 1:
                    errors.append("max_features must be >= 1")
            except (ValueError, TypeError):
                errors.append("max_features must be an integer")

        estimator = params.get("estimator", "decision_tree")
        if estimator not in ("decision_tree", "random_forest"):
            errors.append("estimator must be 'decision_tree' or 'random_forest'")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: NodeContext) -> NodeResult:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.tree import DecisionTreeClassifier

        params = context.params
        importance_threshold = float(params.get("importance_threshold", 0.01))
        max_features = params.get("max_features")
        estimator_type = params.get("estimator", "decision_tree")
        random_seed = int(params.get("random_seed", 42))

        prepared = prepare_supervised_training_data(
            context.inputs,
            operation="feature_selection_embedded",
        )
        df = prepared.frame
        features = prepared.feature_columns(params)
        y_binary = prepared.y_binary

        train_art = context.inputs.require("train", "feature_selection_embedded")
        def_art = context.inputs.first("definition")

        X = df.select(features).to_numpy()

        if estimator_type == "random_forest":
            clf = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=random_seed, n_jobs=-1)
        else:
            clf = DecisionTreeClassifier(max_depth=5, min_samples_leaf=5, random_state=random_seed)

        clf.fit(X, y_binary)

        importances = clf.feature_importances_
        importance_map = {
            feat: round(float(imp), 6)
            for feat, imp in zip(features, importances, strict=False)
        }

        sorted_features = sorted(importance_map.items(), key=lambda x: x[1], reverse=True)

        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        for feat, imp in sorted_features:
            if imp >= importance_threshold:
                selected.append({
                    "variable": feat,
                    "reason": f"Importance {imp:.6f} >= threshold {importance_threshold}",
                    "method": "embedded",
                    "score": imp,
                })
            else:
                rejected.append({
                    "variable": feat,
                    "reason": f"Importance {imp:.6f} < threshold {importance_threshold}",
                    "method": "embedded",
                    "score": imp,
                })

        if max_features and len(selected) > max_features:
            overflow = selected[max_features:]
            selected = selected[:max_features]
            for entry in overflow:
                rejected.append({
                    "variable": entry["variable"],
                    "reason": f"Exceeds max_features={max_features}",
                    "method": "max_features",
                    "score": entry.get("score", 0.0),
                })

        selection = {
            "method": "embedded",
            "estimator": estimator_type,
            "params": {
                "importance_threshold": importance_threshold,
                "max_features": max_features,
                "random_seed": random_seed,
            },
            "selected": selected,
            "rejected": rejected,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "source_artifact_id": train_art.artifact_id,
        }

        if def_art:
            try:
                selection = merge_selection_definition(
                    context.inputs, def_art,
                    key="selection_embedded", selection=selection,
                )
            except (KeyError, TypeError, AttributeError):
                logger.warning("Could not merge existing selection definition", exc_info=True)

        context.outputs.publish_json(
            role="definition",
            kind=EvidenceKind.SELECTION_DEFINITION,
            payload=selection,
            metadata={"method": "embedded", "selected_count": len(selected)},
        )

        importance_report = {
            "method": "embedded",
            "estimator": estimator_type,
            "feature_importance": importance_map,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "importance_threshold": importance_threshold,
        }
        context.outputs.publish_json(
            role="report",
            kind=EvidenceKind.FEATURE_SELECTION_EVIDENCE,
            payload=importance_report,
            metadata={"estimator": estimator_type},
        )

        context.outputs.add_metric("selected_count", len(selected))
        context.outputs.add_metric("rejected_count", len(rejected))
        return context.outputs.build_result()


__definition__ = NodeDefinition(
    node_type=FeatureSelectionEmbeddedNode.node_type,
    version=FeatureSelectionEmbeddedNode.version,
    category=FeatureSelectionEmbeddedNode.category,
    description="",
    input_contract=ArtifactContract(
        roles=tuple(ArtifactRoleSpec(r, required=True) for r in FeatureSelectionEmbeddedNode.input_roles),
    ),
    output_contract=ArtifactContract(
        roles=tuple(ArtifactRoleSpec(r, required=True) for r in FeatureSelectionEmbeddedNode.output_roles),
    ),
    parameter_schema=None,
    optional_dependencies=(),
    tier="launch",
)
