"""Node types API — expose method metadata for UI consumption.

Phase 6 adds:
- GET /node-types — list all registered node types with metadata
- GET /node-types/{node_type}/schema — parameter schema for a node type
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cardre.registry import NodeRegistry
from sidecar.models import NodeTypeListResponse, NodeTypeItem, NodeTypeSchemaResponse

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
    "cardre.auto_binning_fit": {
        "model_family": None,
        "feature_strategies": [],
        "interpretability_level": None,
        "champion_eligibility": None,
        "description": "Supervised optimal binning using optbinning engine.",
        "optional_dependencies": ["optimal-binning"],
    },
}


def _get_registry() -> NodeRegistry:
    return NodeRegistry.with_defaults()


@router.get("/node-types", response_model=NodeTypeListResponse)
def list_node_types() -> NodeTypeListResponse:
    """List all registered node types with method metadata."""
    registry = _get_registry()
    items: list[NodeTypeItem] = []

    for node_type in sorted(registry.list_types()):
        cls = registry.resolve(node_type)
        meta = _MODEL_FAMILIES.get(node_type, {})

        items.append(NodeTypeItem(
            node_type=node_type,
            version=getattr(cls, "version", "1"),
            category=getattr(cls, "category", "unknown"),
            description=meta.get("description", ""),
            model_family=meta.get("model_family"),
            feature_strategies=meta.get("feature_strategies", []),
            interpretability_level=meta.get("interpretability_level"),
            champion_eligibility=meta.get("champion_eligibility"),
            optional_dependencies=meta.get("optional_dependencies", []),
            input_roles=getattr(cls, "input_roles", []),
            output_roles=getattr(cls, "output_roles", []),
        ))

    return NodeTypeListResponse(node_types=items, count=len(items))


@router.get("/node-types/{node_type:path}/schema", response_model=NodeTypeSchemaResponse)
def get_node_type_schema(node_type: str) -> NodeTypeSchemaResponse:
    """Get parameter schema for a specific node type."""
    registry = _get_registry()

    if not registry.has(node_type):
        raise HTTPException(status_code=404, detail={"code": "NODE_TYPE_NOT_FOUND", "message": f"Unknown node type: {node_type!r}"})

    cls = registry.resolve(node_type)
    instance = cls()
    meta = _MODEL_FAMILIES.get(node_type, {})

    # Extract defaults and schema from validate_params
    defaults: dict = {}
    params_schema: dict = {}

    # Provide known parameter schemas for model nodes
    if node_type == "cardre.logistic_regression":
        params_schema = {
            "penalty": {"type": "string", "enum": ["l1", "l2", "elasticnet", None], "default": "l2"},
            "solver": {"type": "string", "enum": ["lbfgs", "liblinear", "newton-cg", "newton-cholesky", "sag", "saga"], "default": "lbfgs"},
            "C": {"type": "number", "default": 1.0, "minimum": 0},
            "max_iter": {"type": "integer", "default": 100, "minimum": 1},
        }
        defaults = {"penalty": "l2", "solver": "lbfgs", "C": 1.0, "max_iter": 100}
    elif node_type in ("cardre.decision_tree_classifier", "cardre.random_forest_classifier"):
        params_schema = {
            "feature_strategy": {"type": "string", "enum": ["raw_numeric", "encoded_raw", "woe_challenger"]},
            "max_depth": {"type": "integer", "minimum": 1, "default": None},
            "min_samples_leaf": {"type": "integer", "minimum": 1, "default": 1},
            "class_weight": {"type": ["string", "object", "null"], "default": None},
            "random_seed": {"type": "integer", "default": 42},
        }
        defaults = {"feature_strategy": "raw_numeric", "min_samples_leaf": 1, "random_seed": 42}
        if node_type == "cardre.random_forest_classifier":
            params_schema["n_estimators"] = {"type": "integer", "minimum": 1, "default": 100}
            defaults["n_estimators"] = 100
    elif node_type == "cardre.gradient_boosting_classifier":
        params_schema = {
            "feature_strategy": {"type": "string", "enum": ["raw_numeric", "encoded_raw", "woe_challenger"]},
            "n_estimators": {"type": "integer", "minimum": 1, "default": 100},
            "max_depth": {"type": "integer", "minimum": 1, "default": 3},
            "learning_rate": {"type": "number", "default": 0.1, "exclusiveMinimum": 0},
            "min_samples_leaf": {"type": "integer", "minimum": 1, "default": 1},
            "random_seed": {"type": "integer", "default": 42},
        }
        defaults = {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.1, "min_samples_leaf": 1, "random_seed": 42}
    elif node_type == "cardre.validation_metrics":
        params_schema = {
            "cutoffs": {"type": "array", "items": {"type": "number"}, "default": [0.5]},
        }
        defaults = {"cutoffs": [0.5]}
    elif node_type == "cardre.threshold_optimization":
        params_schema = {
            "objective": {"type": "string", "enum": ["youden", "max_f1", "max_g_mean", "cost_minimize"], "default": "youden"},
            "n_thresholds": {"type": "integer", "minimum": 10, "default": 200},
            "cost_fp": {"type": "number", "default": 1.0},
            "cost_fn": {"type": "number", "default": 10.0},
        }
        defaults = {"objective": "youden", "n_thresholds": 200}
    elif node_type == "cardre.model_explainability":
        params_schema = {
            "include_permutation_importance": {"type": "boolean", "default": False},
        }
        defaults = {"include_permutation_importance": False}
    elif node_type == "cardre.model_limitations":
        params_schema = {
            "accepted_limitations": {"type": "array", "items": {"type": "string"}, "default": []},
        }
        defaults = {"accepted_limitations": []}
    elif node_type == "cardre.voting_ensemble":
        params_schema = {
            "model_artifact_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2},
            "voting": {"type": "string", "enum": ["hard", "soft"], "default": "soft"},
            "threshold": {"type": "number", "default": 0.5, "minimum": 0, "maximum": 1},
        }
        defaults = {"voting": "soft", "threshold": 0.5}
    elif node_type == "cardre.weighted_ensemble":
        params_schema = {
            "model_artifact_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2},
            "weights": {"type": "array", "items": {"type": "number"}},
            "optimize_weights": {"type": "boolean", "default": False},
        }
        defaults = {"optimize_weights": False}
    elif node_type == "cardre.auto_binning_fit":
        params_schema = {
            "engine": {"type": "string", "enum": ["optbinning"], "default": "optbinning"},
            "prebinning_method": {"type": "string", "enum": ["cart", "quantile"], "default": "cart"},
            "solver": {"type": "string", "enum": ["cp", "mip"], "default": "cp"},
            "divergence": {"type": "string", "enum": ["iv", "js", "hellinger"], "default": "iv"},
            "max_n_prebins": {"type": "integer", "minimum": 2, "default": 20},
            "min_prebin_size": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.05},
            "max_n_bins": {"type": "integer", "minimum": 2, "default": 6},
            "min_bin_size": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.03},
            "min_bin_n_event": {"type": "integer", "minimum": 1, "default": 20},
            "min_bin_n_nonevent": {"type": "integer", "minimum": 1, "default": 20},
            "monotonic_trend": {"type": "string", "enum": ["auto", "none", "ascending", "descending"], "default": "auto"},
            "cat_cutoff": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.01},
            "time_limit": {"type": "integer", "minimum": 1, "default": 100},
            "special_codes": {"type": "object", "default": {}},
            "exclude_columns": {"type": "array", "items": {"type": "string"}, "default": []},
        }
        defaults = {
            "engine": "optbinning", "prebinning_method": "cart", "solver": "cp",
            "divergence": "iv", "max_n_prebins": 20, "min_prebin_size": 0.05,
            "max_n_bins": 6, "min_bin_size": 0.03, "min_bin_n_event": 20,
            "min_bin_n_nonevent": 20, "monotonic_trend": "auto", "cat_cutoff": 0.01,
            "time_limit": 100, "special_codes": {}, "exclude_columns": [],
        }
    elif node_type == "cardre.hyperparameter_tuning":
        params_schema = {
            "estimator_type": {"type": "string", "enum": ["decision_tree", "random_forest", "gbdt", "logistic_regression"]},
            "search_method": {"type": "string", "enum": ["grid", "randomized"], "default": "grid"},
            "param_grid": {"type": "object"},
            "cv_folds": {"type": "integer", "minimum": 2, "default": 5},
            "scoring": {"type": "string", "default": "roc_auc"},
            "n_jobs": {"type": "integer", "default": -1},
            "n_iter": {"type": "integer", "minimum": 1, "default": 10},
            "refit": {"type": "boolean", "default": True},
            "random_seed": {"type": "integer", "default": 42},
            "feature_strategy": {"type": "string", "enum": ["raw_numeric", "encoded_raw", "woe_challenger"], "default": "raw_numeric"},
        }
        defaults = {"search_method": "grid", "cv_folds": 5, "scoring": "roc_auc", "n_jobs": -1, "n_iter": 10, "refit": True, "random_seed": 42, "feature_strategy": "raw_numeric"}

    return NodeTypeSchemaResponse(
        node_type=node_type,
        version=getattr(cls, "version", "1"),
        params_schema=params_schema,
        defaults=defaults,
        description=meta.get("description", ""),
    )
