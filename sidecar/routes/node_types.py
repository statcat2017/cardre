"""Node types API — expose method metadata for UI consumption.

Phase 6 adds:
- GET /node-types — list all registered node types with metadata
- GET /node-types/{node_type}/schema — parameter schema for a node type
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)
from cardre.registry import NodeRegistry
from sidecar.models import (
    MethodOptionResponse,
    NodeTypeListResponse,
    NodeTypeItem,
    NodeTypeSchemaResponse,
    ParameterConstraintResponse,
    ParameterDefinitionResponse,
)

router = APIRouter(tags=["node-types"])

# Model family metadata for display
_MODEL_FAMILIES: dict[str, dict] = {
    "cardre.logistic_regression": {
        "model_family": "logistic_regression",
        "feature_strategies": ["woe"],
        "interpretability_level": "native_scorecard",
        "champion_eligibility": "fully_eligible",
        "description": "Logistic regression with WOE features. Fully interpretable scorecard.",
    },
    "cardre.decision_tree_classifier": {
        "model_family": "decision_tree",
        "feature_strategies": ["raw_numeric", "encoded_raw", "woe_challenger"],
        "interpretability_level": "native_interpretable",
        "champion_eligibility": "eligible_with_rule_report",
        "description": "Decision tree with human-readable rule export.",
    },
    "cardre.random_forest_classifier": {
        "model_family": "random_forest",
        "feature_strategies": ["raw_numeric", "encoded_raw", "woe_challenger"],
        "interpretability_level": "native_semi_transparent",
        "champion_eligibility": "eligible_with_limitation_evidence",
        "description": "Random forest ensemble. Feature importance available, individual predictions not fully decomposable.",
    },
    "cardre.gradient_boosting_classifier": {
        "model_family": "gbdt",
        "feature_strategies": ["raw_numeric", "encoded_raw", "woe_challenger"],
        "interpretability_level": "native_semi_transparent",
        "champion_eligibility": "eligible_with_limitation_evidence",
        "description": "Sklearn gradient boosting. Feature importance available, individual predictions not fully decomposable.",
    },
    "cardre.xgboost_classifier": {
        "model_family": "xgboost",
        "feature_strategies": ["raw_numeric", "encoded_raw", "woe_challenger"],
        "interpretability_level": "native_semi_transparent",
        "champion_eligibility": "eligible_with_limitation_evidence",
        "description": "XGBoost classifier. Requires xgboost package.",
        "optional_dependencies": ["boosting"],
    },
    "cardre.lightgbm_classifier": {
        "model_family": "lightgbm",
        "feature_strategies": ["raw_numeric", "encoded_raw", "woe_challenger"],
        "interpretability_level": "native_semi_transparent",
        "champion_eligibility": "eligible_with_limitation_evidence",
        "description": "LightGBM classifier. Requires lightgbm package.",
        "optional_dependencies": ["boosting"],
    },
    "cardre.catboost_classifier": {
        "model_family": "catboost",
        "feature_strategies": ["raw_numeric", "encoded_raw", "woe_challenger"],
        "interpretability_level": "native_semi_transparent",
        "champion_eligibility": "eligible_with_limitation_evidence",
        "description": "CatBoost classifier. Requires catboost package.",
        "optional_dependencies": ["boosting"],
    },
    "cardre.model_explainability": {
        "model_family": None,
        "feature_strategies": [],
        "interpretability_level": None,
        "champion_eligibility": None,
        "description": "Produce explainability report for a fitted model.",
    },
    "cardre.model_limitations": {
        "model_family": None,
        "feature_strategies": [],
        "interpretability_level": None,
        "champion_eligibility": None,
        "description": "Produce structured limitations report for a fitted model.",
    },
    "cardre.voting_ensemble": {
        "model_family": "voting_ensemble",
        "feature_strategies": ["ensemble"],
        "interpretability_level": "post_hoc_only",
        "champion_eligibility": "not_recommended",
        "description": "Hard or soft voting ensemble across fitted model artifacts. Experimental/research.",
    },
    "cardre.weighted_ensemble": {
        "model_family": "weighted_ensemble",
        "feature_strategies": ["ensemble"],
        "interpretability_level": "post_hoc_only",
        "champion_eligibility": "not_recommended",
        "description": "Weighted ensemble with user-defined or validation-optimized weights. Experimental/research.",
    },
    "cardre.validation_metrics": {
        "model_family": None,
        "feature_strategies": [],
        "interpretability_level": None,
        "champion_eligibility": None,
        "description": "Compute validation metrics including AUC, KS, precision, recall, F1, G-Mean, and confusion matrix.",
    },
    "cardre.threshold_optimization": {
        "model_family": None,
        "feature_strategies": [],
        "interpretability_level": None,
        "champion_eligibility": None,
        "description": "Optimize classification threshold using Youden, max F1, max G-Mean, or cost minimization.",
    },
    "cardre.hyperparameter_tuning": {
        "model_family": None,
        "feature_strategies": [],
        "interpretability_level": None,
        "champion_eligibility": None,
        "description": "Hyperparameter tuning using GridSearchCV / RandomizedSearchCV for decision tree, random forest, GBDT, or logistic regression.",
    },
    "cardre.binning": {
        "model_family": None,
        "feature_strategies": [],
        "interpretability_level": None,
        "champion_eligibility": None,
        "description": "Canonical binning node supporting Fine Classing and OptBinning methods.",
    },
}


def _get_registry() -> NodeRegistry:
    return NodeRegistry.with_defaults()


@router.get("/node-types", response_model=NodeTypeListResponse)
def list_node_types(
    available_only: bool = Query(default=False, description="Exclude unavailable nodes"),
) -> NodeTypeListResponse:
    if not isinstance(available_only, bool):
        available_only = False
    registry = _get_registry()
    items: list[NodeTypeItem] = []

    for node_type in sorted(registry.list_types()):
        cls = registry.resolve(node_type)
        if getattr(cls, "is_internal", False):
            continue
        meta = _MODEL_FAMILIES.get(node_type, {})
        av = registry.availability(node_type)
        if available_only and not av.available:
            continue

        items.append(NodeTypeItem(
            node_type=node_type,
            version=getattr(cls, "version", "1"),
            category=getattr(cls, "category", "unknown"),
            tier=av.tier,
            available=av.available,
            disabled_reason=av.disabled_reason,
            missing_optional_dependencies=av.missing_optional_dependencies,
            description=getattr(cls, "description", None) or meta.get("description", ""),
            model_family=getattr(cls, "model_family", None) or meta.get("model_family"),
            feature_strategies=getattr(cls, "feature_strategies", None) or meta.get("feature_strategies", []),
            interpretability_level=getattr(cls, "interpretability_level", None) or meta.get("interpretability_level"),
            champion_eligibility=getattr(cls, "champion_eligibility", None) or meta.get("champion_eligibility"),
            optional_dependencies=getattr(cls, "optional_dependencies", None) or meta.get("optional_dependencies", []),
            input_roles=getattr(cls, "input_roles", []),
            output_roles=getattr(cls, "output_roles", []),
        ))

    return NodeTypeListResponse(node_types=items, count=len(items))


# Helper: convert schema dataclasses to Pydantic response models


def _constraint_to_response(c: ParameterConstraint | None) -> ParameterConstraintResponse | None:
    if c is None:
        return None
    return ParameterConstraintResponse(
        required=c.required,
        min_value=c.min_value,
        max_value=c.max_value,
        exclusive_min=c.exclusive_min,
        exclusive_max=c.exclusive_max,
        min_length=c.min_length,
        max_length=c.max_length,
        min_items=c.min_items,
        max_items=c.max_items,
        enum_values=c.enum_values,
        pattern=c.pattern,
    )


def _definition_to_response(d: ParameterDefinition) -> ParameterDefinitionResponse:
    return ParameterDefinitionResponse(
        name=d.name,
        label=d.label,
        kind=d.kind,
        default=d.default,
        required=d.required,
        constraint=_constraint_to_response(d.constraint),
        help_text=d.help_text,
        group=d.group,
    )


def _method_to_response(m: MethodOption) -> MethodOptionResponse:
    return MethodOptionResponse(
        id=m.id,
        label=m.label,
        status=m.status,
        params=[_definition_to_response(p) for p in m.params],
        description=m.description,
    )


@router.get("/node-types/{node_type:path}/schema", response_model=NodeTypeSchemaResponse)
def get_node_type_schema(node_type: str) -> NodeTypeSchemaResponse:
    """Get parameter schema for a specific node type."""
    registry = _get_registry()

    if not registry.has(node_type):
        raise HTTPException(
            status_code=404,
            detail={"code": "NODE_TYPE_NOT_FOUND", "message": f"Unknown node type: {node_type!r}"},
        )

    cls = registry.resolve(node_type)
    meta = _MODEL_FAMILIES.get(node_type, {})

    schema: NodeParameterSchema = cls.parameter_schema()

    methods = [_method_to_response(m) for m in schema.methods]

    # Legacy flat fields from the first available method
    params_schema: dict = {}
    defaults: dict = {}
    if methods and methods[0].status == "available":
        for p in methods[0].params:
            param_type = p.kind
            entry: dict = {"type": param_type}
            if p.default is not None or p.required:
                entry["default"] = p.default
            if p.constraint:
                if p.constraint.min_value is not None:
                    entry["minimum"] = p.constraint.min_value
                if p.constraint.max_value is not None:
                    entry["maximum"] = p.constraint.max_value
                if p.constraint.exclusive_min is not None:
                    entry["exclusiveMinimum"] = p.constraint.exclusive_min
                if p.constraint.exclusive_max is not None:
                    entry["exclusiveMaximum"] = p.constraint.exclusive_max
                if p.constraint.enum_values is not None:
                    entry["enum"] = p.constraint.enum_values
                if p.constraint.min_items is not None:
                    entry["minItems"] = p.constraint.min_items
                if p.constraint.max_items is not None:
                    entry["maxItems"] = p.constraint.max_items
            params_schema[p.name] = entry
            if p.default is not None:
                defaults[p.name] = p.default
            elif p.required:
                defaults[p.name] = None

    av = registry.availability(node_type)
    return NodeTypeSchemaResponse(
        node_type=node_type,
        version=schema.node_version,
        title=schema.title,
        methods=methods,
        params_schema=params_schema,
        defaults=defaults,
        description=meta.get("description", ""),
        available=av.available,
        disabled_reason=av.disabled_reason,
    )
