"""Comparison content builders — pure functions, no DB/filesystem access.

Each builder takes a typed evidence lookup callable and returns a content
dict. They are pure with respect to persistence: no UoW, no ``_conn``, no
artifact store. ``RefreshComparison`` invokes them and owns the publication +
snapshot persistence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cardre.domain.evidence.kinds import EvidenceKind

EvidenceLookup = Callable[
    [list[dict[str, Any]], str, str, str | None, tuple[EvidenceKind, ...]],
    dict[str, Any] | None,
]


def find_artifact(
    lookup: EvidenceLookup,
    step_map: list[dict[str, Any]],
    cs: str,
    pv_id: str,
    evidence_branch_id: str | None,
    kinds: tuple[EvidenceKind, ...],
) -> dict[str, Any] | None:
    for kind in kinds:
        result = lookup(step_map, cs, pv_id, evidence_branch_id, (kind,))
        if result is not None:
            return result
    return None


def build_woe_iv(
    lookup: EvidenceLookup,
    step_map_baseline: list[dict[str, Any]],
    step_map_challenger: list[dict[str, Any]],
    pv_id_baseline: str,
    pv_id_challenger: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_woe_iv"):
        return {"variables": []}

    woe_b = find_artifact(lookup, step_map_baseline, "final-woe-iv", pv_id_baseline, None, (EvidenceKind.WOE_IV_EVIDENCE,))
    woe_c = find_artifact(lookup, step_map_challenger, "final-woe-iv", pv_id_challenger, branch_id_challenger, (EvidenceKind.WOE_IV_EVIDENCE,))

    if not woe_b or not woe_c:
        return {"variables": []}

    b_vars = {}
    c_vars = {}
    for v in woe_b.get("variables", []):
        if isinstance(v, dict) and "variable" in v:
            b_vars[v["variable"]] = v
    for v in woe_c.get("variables", []):
        if isinstance(v, dict) and "variable" in v:
            c_vars[v["variable"]] = v

    all_vars = sorted(set(b_vars) | set(c_vars))
    woe_vars = []
    for var_name in all_vars:
        bv = b_vars.get(var_name, {})
        cv = c_vars.get(var_name, {})
        woe_vars.append({
            "variable": var_name,
            "baseline": {
                "iv": bv.get("iv", 0),
                "bin_count": len(bv.get("bins", [])),
                "zero_cell_warning_count": len([w for w in bv.get("warnings", []) if "zero" in str(w).lower()]),
                "sparse_bin_warning_count": len([w for w in bv.get("warnings", []) if "sparse" in str(w).lower()]),
                "monotonicity_warning": any("monotonic" in str(w).lower() for w in bv.get("warnings", [])),
            },
            "challengers": {
                branch_id_challenger: {
                    "iv": cv.get("iv", 0),
                    "bin_count": len(cv.get("bins", [])),
                    "zero_cell_warning_count": len([w for w in cv.get("warnings", []) if "zero" in str(w).lower()]),
                    "sparse_bin_warning_count": len([w for w in cv.get("warnings", []) if "sparse" in str(w).lower()]),
                    "monotonicity_warning": any("monotonic" in str(w).lower() for w in cv.get("warnings", [])),
                },
            },
            "difference": {
                "iv_delta_vs_baseline": cv.get("iv", 0) - bv.get("iv", 0),
                "bin_count_delta_vs_baseline": len(cv.get("bins", [])) - len(bv.get("bins", [])),
            },
        })
    return {"variables": woe_vars}


def build_model(
    lookup: EvidenceLookup,
    step_map_baseline: list[dict[str, Any]],
    step_map_challenger: list[dict[str, Any]],
    pv_id_baseline: str,
    pv_id_challenger: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_model"):
        return {"variables": [], "branch_level": {}}

    lr_b = find_artifact(
        lookup, step_map_baseline, "model-fit", pv_id_baseline, None,
        (EvidenceKind.MODEL_ARTIFACT,),
    )
    lr_c = find_artifact(
        lookup, step_map_challenger, "model-fit", pv_id_challenger, branch_id_challenger,
        (EvidenceKind.MODEL_ARTIFACT,),
    )

    if not lr_b or not lr_c:
        return {"variables": [], "branch_level": {}}

    from cardre.modeling.families import require as require_family

    b_family = lr_b.get("model_family", "logistic_regression")
    c_family = lr_c.get("model_family", "logistic_regression")
    b_model_payload = lr_b.get("model_payload", {})
    c_model_payload = lr_c.get("model_payload", {})
    if not isinstance(b_model_payload, dict):
        b_model_payload = {}
    if not isinstance(c_model_payload, dict):
        c_model_payload = {}
    b_features = lr_b.get("feature_contract", {}).get("features", lr_b.get("features", []))
    c_features = lr_c.get("feature_contract", {}).get("features", lr_c.get("features", []))
    b_spec = require_family(b_family)
    c_spec = require_family(c_family)

    result: dict[str, Any] = {
        "branch_level": {
            "baseline": {
                "model_family": b_family,
                "feature_count": len(b_features),
                "intercept": b_model_payload.get("intercept", lr_b.get("intercept")),
                "warnings": lr_b.get("warnings", []),
            },
            branch_id_challenger: {
                "model_family": c_family,
                "feature_count": len(c_features),
                "intercept": c_model_payload.get("intercept", lr_c.get("intercept")),
                "warnings": lr_c.get("warnings", []),
            },
        },
    }

    if b_spec.has_coefficients and c_spec.has_coefficients:
        b_coeffs_value = b_model_payload.get("coefficients", lr_b.get("coefficients", []))
        c_coeffs_value = c_model_payload.get("coefficients", lr_c.get("coefficients", []))
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
            b_val = (
                b_coeffs.get(var_name, 0) if isinstance(b_coeffs.get(var_name), (int, float))
                else b_coeffs.get(var_name, {}).get("coefficient", 0)
            )
            c_val = (
                c_coeffs.get(var_name, 0) if isinstance(c_coeffs.get(var_name), (int, float))
                else c_coeffs.get(var_name, {}).get("coefficient", 0)
            )
            model_vars.append({
                "variable": var_name,
                "baseline": {"included": var_name in b_coeffs, "coefficient": b_val, "points_range": 0},
                "challengers": {branch_id_challenger: {"included": var_name in c_coeffs, "coefficient": c_val, "points_range": 0}},
                "difference": {"coefficient_delta_vs_baseline": c_val - b_val},
            })
        result["variables"] = model_vars
    else:
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


def build_validation(
    lookup: EvidenceLookup,
    step_map_baseline: list[dict[str, Any]],
    step_map_challenger: list[dict[str, Any]],
    pv_id_baseline: str,
    pv_id_challenger: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_validation"):
        return {"roles": {"train": {}, "test": {}, "oot": {}}}

    vm_b = find_artifact(
        lookup, step_map_baseline, "validation-metrics", pv_id_baseline, None,
        (EvidenceKind.VALIDATION_METRICS,),
    )
    vm_c = find_artifact(
        lookup, step_map_challenger, "validation-metrics", pv_id_challenger, branch_id_challenger,
        (EvidenceKind.VALIDATION_METRICS,),
    )

    def _roles(payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        r = payload.get("roles")
        if isinstance(r, dict):
            return r
        metrics_by_role = payload.get("metrics_by_role")
        if isinstance(metrics_by_role, dict):
            return metrics_by_role
        metrics = payload.get("metrics")
        if isinstance(metrics, dict):
            return metrics
        return payload

    b_roles = _roles(vm_b)
    c_roles = _roles(vm_c)

    roles: dict[str, Any] = {}
    for role_name in ("train", "test", "oot"):
        b_role = b_roles.get(role_name, {}) if isinstance(b_roles, dict) else {}
        c_role = c_roles.get(role_name, {}) if isinstance(c_roles, dict) else {}
        role_data: dict[str, Any] = {}
        if b_role and isinstance(b_role, dict):
            role_data["baseline"] = {
                "auc": b_role.get("auc"),
                "gini": b_role.get("gini"),
                "ks": b_role.get("ks"),
                "calibration": b_role.get("calibration", {}),
            }
        if c_role and isinstance(c_role, dict):
            role_data[branch_id_challenger] = {
                "auc": c_role.get("auc"),
                "gini": c_role.get("gini"),
                "ks": c_role.get("ks"),
                "calibration": c_role.get("calibration", {}),
            }
        roles[role_name] = role_data
    return {"roles": roles}


def build_cutoff(
    lookup: EvidenceLookup,
    step_map_baseline: list[dict[str, Any]],
    step_map_challenger: list[dict[str, Any]],
    pv_id_baseline: str,
    pv_id_challenger: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_cutoff"):
        return {"roles": {}}

    co_b = find_artifact(
        lookup, step_map_baseline, "cutoff-analysis", pv_id_baseline, None,
        (EvidenceKind.CUTOFF_ANALYSIS,),
    )
    co_c = find_artifact(
        lookup, step_map_challenger, "cutoff-analysis", pv_id_challenger, branch_id_challenger,
        (EvidenceKind.CUTOFF_ANALYSIS,),
    )

    roles: dict[str, Any] = {}
    for role_name in ("train", "test", "oot"):
        b_bands: list[dict[str, Any]] = []
        if isinstance(co_b, dict):
            b_bands = co_b.get(role_name) or co_b.get("bands") or []
        c_bands: list[dict[str, Any]] = []
        if isinstance(co_c, dict):
            c_bands = co_c.get(role_name) or co_c.get("bands") or []

        b_by_cutoff = {b.get("cutoff"): b for b in b_bands if isinstance(b, dict)}
        c_by_cutoff = {c.get("cutoff"): c for c in c_bands if isinstance(c, dict)}
        all_cutoffs = sorted({k for k in set(b_by_cutoff) | set(c_by_cutoff) if k is not None})
        bands = []
        for cutoff in all_cutoffs[:20]:
            b_entry = b_by_cutoff.get(cutoff, {})
            c_entry = c_by_cutoff.get(cutoff, {})
            bands.append({
                "cutoff": cutoff,
                "baseline": {
                    "approval_rate": b_entry.get("approval_rate"),
                    "bad_rate": b_entry.get("bad_rate"),
                    "capture_rate": b_entry.get("capture_rate"),
                    "population_count": b_entry.get("population_count"),
                },
                branch_id_challenger: {
                    "approval_rate": c_entry.get("approval_rate"),
                    "bad_rate": c_entry.get("bad_rate"),
                    "capture_rate": c_entry.get("capture_rate"),
                    "population_count": c_entry.get("population_count"),
                },
            })
        roles[role_name] = bands
    return {"roles": roles}


def build_content(
    lookup: EvidenceLookup,
    step_map_baseline: list[dict[str, Any]],
    step_map_challenger: list[dict[str, Any]],
    pv_id_baseline: str,
    pv_id_challenger: str,
    branch_id_baseline: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    return {
        "comparison_type": "challenger_vs_baseline",
        "baseline_branch_id": branch_id_baseline,
        "challenger_branch_id": branch_id_challenger,
        "woe_iv": build_woe_iv(
            lookup, step_map_baseline, step_map_challenger,
            pv_id_baseline, pv_id_challenger, branch_id_challenger, spec,
        ),
        "model": build_model(
            lookup, step_map_baseline, step_map_challenger,
            pv_id_baseline, pv_id_challenger, branch_id_challenger, spec,
        ),
        "validation": build_validation(
            lookup, step_map_baseline, step_map_challenger,
            pv_id_baseline, pv_id_challenger, branch_id_challenger, spec,
        ),
        "cutoff": build_cutoff(
            lookup, step_map_baseline, step_map_challenger,
            pv_id_baseline, pv_id_challenger, branch_id_challenger, spec,
        ),
        "warnings": [],
    }


__all__ = [
    "build_content",
    "build_cutoff",
    "build_model",
    "build_validation",
    "build_woe_iv",
    "find_artifact",
]
