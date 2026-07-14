"""Validation metrics comparison section collector."""

from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.services.comparison.resolver import find_typed_artifact, get_step_maps
from cardre.store.db import ProjectStore


def _validation_roles(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    roles = payload.get("roles")
    if isinstance(roles, dict):
        return roles
    metrics_by_role = payload.get("metrics_by_role")
    if isinstance(metrics_by_role, dict):
        return metrics_by_role
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return payload


def build_validation_comparison(
    store: ProjectStore,
    plan_version_id_baseline: str,
    plan_version_id_challenger: str,
    branch_id_baseline: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_validation"):
        return {"roles": {"train": {}, "test": {}, "oot": {}}}

    step_map_b, step_map_c = get_step_maps(
        store, plan_version_id_baseline, plan_version_id_challenger,
        branch_id_baseline, branch_id_challenger,
    )

    vm_b = find_typed_artifact(store, step_map_b, "validation-metrics", plan_version_id_baseline, None, (EvidenceKind.VALIDATION_METRICS, EvidenceKind.VALIDATION_EVIDENCE))
    vm_c = find_typed_artifact(store, step_map_c, "validation-metrics", plan_version_id_challenger, branch_id_challenger, (EvidenceKind.VALIDATION_METRICS, EvidenceKind.VALIDATION_EVIDENCE))
    vm_b_roles = _validation_roles(vm_b)
    vm_c_roles = _validation_roles(vm_c)

    roles: dict[str, Any] = {}
    for role_name in ("train", "test", "oot"):
        b_role = vm_b_roles.get(role_name, {}) if isinstance(vm_b_roles, dict) else {}
        c_role = vm_c_roles.get(role_name, {}) if isinstance(vm_c_roles, dict) else {}
        role_data = {}
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
