"""Cutoff analysis comparison section collector."""

from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.services.comparison.resolver import find_typed_artifact, get_step_maps
from cardre.store.db import ProjectStore


def build_cutoff_comparison(
    store: ProjectStore,
    plan_version_id_baseline: str,
    plan_version_id_challenger: str,
    branch_id_baseline: str,
    branch_id_challenger: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_cutoff"):
        return {"roles": {}}

    step_map_b, step_map_c = get_step_maps(
        store, plan_version_id_baseline, plan_version_id_challenger,
        branch_id_baseline, branch_id_challenger,
    )

    co_b = find_typed_artifact(store, step_map_b, "cutoff-analysis", plan_version_id_baseline, None, (EvidenceKind.CUTOFF_ANALYSIS,))
    co_c = find_typed_artifact(store, step_map_c, "cutoff-analysis", plan_version_id_challenger, branch_id_challenger, (EvidenceKind.CUTOFF_ANALYSIS,))

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
