"""WOE/IV comparison section collector."""

from __future__ import annotations

from typing import Any

from cardre._evidence.kinds import EvidenceKind
from cardre.services.comparison.resolver import ComparisonContext, find_typed_artifact


def build_woe_iv_comparison(
    ctx: ComparisonContext,
    spec: dict[str, Any],
) -> dict[str, Any]:
    if not spec.get("include_woe_iv"):
        return {"variables": []}

    woe_b = find_typed_artifact(ctx.store, ctx.step_map_baseline, "final-woe-iv", ctx.plan_version_id_baseline, None, (EvidenceKind.WOE_IV_EVIDENCE,))
    woe_c = find_typed_artifact(ctx.store, ctx.step_map_challenger, "final-woe-iv", ctx.plan_version_id_challenger, ctx.branch_id_challenger, (EvidenceKind.WOE_IV_EVIDENCE,))

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
                ctx.branch_id_challenger: {
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
