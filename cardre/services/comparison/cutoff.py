"""Cutoff analysis comparison section collector."""

from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.services.comparison.resolver import ComparisonContext, find_typed_artifact


def build_cutoff_comparison(
    ctx: ComparisonContext,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_cutoff"):
        return {"roles": {}}

    co_b = find_typed_artifact(ctx.store, ctx.step_map_baseline, "cutoff-analysis", ctx.plan_version_id_baseline, None, (EvidenceKind.CUTOFF_ANALYSIS,))
    co_c = find_typed_artifact(ctx.store, ctx.step_map_challenger, "cutoff-analysis", ctx.plan_version_id_challenger, ctx.branch_id_challenger, (EvidenceKind.CUTOFF_ANALYSIS,))

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
                ctx.branch_id_challenger: {
                    "approval_rate": c_entry.get("approval_rate"),
                    "bad_rate": c_entry.get("bad_rate"),
                    "capture_rate": c_entry.get("capture_rate"),
                    "population_count": c_entry.get("population_count"),
                },
            })
        roles[role_name] = bands
    return {"roles": roles}
