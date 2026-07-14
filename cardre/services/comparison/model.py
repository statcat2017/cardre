"""Model comparison section collector."""

from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.services.comparison.resolver import find_typed_artifact, get_step_maps
from cardre.store.db import ProjectStore


def build_model_comparison(
    store: ProjectStore,
    plan_version_id_baseline: str,
    plan_version_id_challenger: str,
    branch_id_baseline: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_model"):
        return {"variables": [], "branch_level": {}}

    step_map_b, step_map_c = get_step_maps(
        store, plan_version_id_baseline, plan_version_id_challenger,
        branch_id_baseline, branch_id_challenger,
    )

    lr_b = find_typed_artifact(store, step_map_b, "model-fit", plan_version_id_baseline, None, (EvidenceKind.MODEL_ARTIFACT, EvidenceKind.ENSEMBLE_MODEL_ARTIFACT))
    lr_c = find_typed_artifact(store, step_map_c, "model-fit", plan_version_id_challenger, branch_id_challenger, (EvidenceKind.MODEL_ARTIFACT, EvidenceKind.ENSEMBLE_MODEL_ARTIFACT))

    if not lr_b or not lr_c:
        return {"variables": [], "branch_level": {}}

    b_family = lr_b.get("model_family", "logistic_regression")
    c_family = lr_c.get("model_family", "logistic_regression")

    result: dict[str, Any] = {
        "branch_level": {
            "baseline": {
                "model_family": b_family,
                "feature_count": len(lr_b.get("features", lr_b.get("feature_contract", {}).get("features", []))),
                "warnings": lr_b.get("warnings", []),
            },
            branch_id_challenger: {
                "model_family": c_family,
                "feature_count": len(lr_c.get("features", lr_c.get("feature_contract", {}).get("features", []))),
                "warnings": lr_c.get("warnings", []),
            },
        },
    }

    if b_family == "logistic_regression" and c_family == "logistic_regression":
        b_coeffs_value = lr_b.get("coefficients", [])
        c_coeffs_value = lr_c.get("coefficients", [])
        b_coeffs = {}
        c_coeffs = {}
        if isinstance(b_coeffs_value, dict):
            b_coeffs = b_coeffs_value
        else:
            for c in b_coeffs_value:
                if isinstance(c, dict) and "variable" in c:
                    b_coeffs[c["variable"]] = c
        if isinstance(c_coeffs_value, dict):
            c_coeffs = c_coeffs_value
        else:
            for c in c_coeffs_value:
                if isinstance(c, dict) and "variable" in c:
                    c_coeffs[c["variable"]] = c

        model_vars = []
        for var_name in sorted(set(b_coeffs) | set(c_coeffs)):
            b_val = b_coeffs.get(var_name, 0) if isinstance(b_coeffs.get(var_name), (int, float)) else b_coeffs.get(var_name, {}).get("coefficient", 0)
            c_val = c_coeffs.get(var_name, 0) if isinstance(c_coeffs.get(var_name), (int, float)) else c_coeffs.get(var_name, {}).get("coefficient", 0)
            model_vars.append({
                "variable": var_name,
                "baseline": {"included": var_name in b_coeffs, "coefficient": b_val, "points_range": 0},
                "challengers": {branch_id_challenger: {"included": var_name in c_coeffs, "coefficient": c_val, "points_range": 0}},
            })
        result["variables"] = model_vars
    else:
        b_features = lr_b.get("features", lr_b.get("feature_contract", {}).get("features", []))
        c_features = lr_c.get("features", lr_c.get("feature_contract", {}).get("features", []))
        b_interp = lr_b.get("interpretability", {})
        c_interp = lr_c.get("interpretability", {})
        result["generic_comparison"] = {
            "baseline": {"model_family": b_family, "features": b_features, "interpretability": b_interp},
            "challenger": {"model_family": c_family, "features": c_features, "interpretability": c_interp},
            "feature_overlap": len(set(b_features) & set(c_features)),
            "baseline_only_features": [f for f in b_features if f not in c_features],
            "challenger_only_features": [f for f in c_features if f not in b_features],
        }

    return result
