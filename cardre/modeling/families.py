"""Model family specification registry — single source of truth for model-family capabilities.

Centralises the model-family-specific logic that was previously scattered
across adapters, explainability, and ensemble modules.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelFamilySpec:
    """Capabilities and metadata for a model family."""
    model_family: str
    display_name: str
    has_coefficients: bool = False
    has_feature_importance: bool = False
    has_tree_rules: bool = False
    native_explanation_type: str = "none"
    shap_explainer_kind: str | None = None
    supports_scorecard_scaling: bool = False
    adapter_fn: str = "apply_sklearn_estimator"


_FAMILIES: dict[str, ModelFamilySpec] = {}


def register(spec: ModelFamilySpec) -> ModelFamilySpec:
    _FAMILIES[spec.model_family] = spec
    return spec


def get(model_family: str) -> ModelFamilySpec | None:
    return _FAMILIES.get(model_family)


def require(model_family: str) -> ModelFamilySpec:
    spec = _FAMILIES.get(model_family)
    if spec is None:
        raise ValueError(
            f"Unsupported model_family {model_family!r}. "
            f"Supported families: {sorted(_FAMILIES)}"
        )
    return spec


def list_families() -> list[str]:
    return list(_FAMILIES.keys())


# ---------------------------------------------------------------------------
# Built-in registrations
# ---------------------------------------------------------------------------

register(ModelFamilySpec(
    model_family="logistic_regression",
    display_name="Logistic Regression",
    has_coefficients=True,
    native_explanation_type="coefficients",
    shap_explainer_kind="LinearExplainer",
    supports_scorecard_scaling=True,
    adapter_fn="apply_logistic",
))

register(ModelFamilySpec(
    model_family="decision_tree",
    display_name="Decision Tree",
    has_tree_rules=True,
    has_feature_importance=True,
    native_explanation_type="tree_rules",
    shap_explainer_kind="TreeExplainer",
    adapter_fn="apply_sklearn_estimator",
))

register(ModelFamilySpec(
    model_family="random_forest",
    display_name="Random Forest",
    has_feature_importance=True,
    native_explanation_type="feature_importance",
    shap_explainer_kind="TreeExplainer",
    adapter_fn="apply_sklearn_estimator",
))

register(ModelFamilySpec(
    model_family="gbdt",
    display_name="Gradient Boosted Decision Tree",
    has_feature_importance=True,
    native_explanation_type="feature_importance",
    shap_explainer_kind="TreeExplainer",
    adapter_fn="apply_sklearn_estimator",
))

for _fam in ("xgboost", "lightgbm", "catboost"):
    register(ModelFamilySpec(
        model_family=_fam,
        display_name=_fam.title(),
        has_feature_importance=True,
        native_explanation_type="feature_importance",
        adapter_fn="apply_sklearn_estimator",
    ))
