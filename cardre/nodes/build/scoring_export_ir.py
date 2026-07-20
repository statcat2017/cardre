"""Compiled scoring intermediate representation — one semantics source.

Both Python and SQL scorecard exporters compile bin definitions, WOE
mappings, feature contracts, and model coefficients into this typed IR,
then render from it.  This ensures parity between the two outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ScoringBin:
    bin_id: str
    woe: float
    kind: Literal["numeric", "categorical"]
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = False
    upper_inclusive: bool = True
    categories: tuple[str, ...] = ()
    is_missing: bool = False
    is_other: bool = False


@dataclass(frozen=True)
class ScoringVariable:
    name: str
    coefficient: float
    missing_policy: Literal["error", "zero"]
    unmatched_policy: Literal["error", "zero"]
    bins: tuple[ScoringBin, ...]


def compile_scorecard(
    bin_def: Any,
    woe_table: Any,
    scorecard_dict: dict[str, Any],
    model_dict: dict[str, Any],
    feature_contract: dict[str, Any] | None = None,
) -> list[ScoringVariable]:
    """Compile bin definitions, WOE mapping, and coefficients into a typed IR.

    Returns one ``ScoringVariable`` per model coefficient.  Raises
    ``ValueError`` if a coefficient exists but has no matching WOE map
    or a scored bin lacks a WOE entry.  Variables present in bins
    but absent from the coefficient map are silently excluded.
    """
    missing_policy: Literal["error", "zero"] = "error"
    if feature_contract:
        mp = feature_contract.get("missing_policy", "error")
        missing_policy = "zero" if mp == "zero" else "error"

    unknown_category_policy = "error"
    if feature_contract:
        unknown_category_policy = feature_contract.get("unknown_category_policy", "error")

    woe_map = woe_table.mapping
    coefficients = model_dict.get("coefficients", {})
    var_defs = bin_def.variables

    variables: list[ScoringVariable] = []
    for vd in var_defs:
        var = vd.variable
        kind = vd.kind
        bins = vd.bins
        woe_key = f"{var}_woe"
        raw_coef = coefficients.get(woe_key)
        if raw_coef is None:
            continue
        coef = float(raw_coef)
        var_woe_map = woe_map.get(var, {})
        if not var_woe_map:
            raise ValueError(
                f"compile_scorecard: coefficient '{woe_key}' has no WOE mapping "
                f"for variable '{var}'"
            )

        compiled_bins: list[ScoringBin] = []
        for be in bins:
            bid = be["bin_id"]
            wv = var_woe_map.get(bid)
            if wv is None:
                raise ValueError(
                    f"compile_scorecard: bin '{bid}' for variable '{var}' "
                    f"has no WOE entry in WOE table"
                )
            if kind == "numeric":
                compiled_bins.append(ScoringBin(
                    bin_id=bid,
                    woe=float(wv),
                    kind="numeric",
                    lower=be.get("lower"),
                    upper=be.get("upper"),
                    lower_inclusive=be.get("lower_inclusive", False),
                    upper_inclusive=be.get("upper_inclusive", True),
                    is_missing=be.get("is_missing_bin", False),
                    is_other=be.get("is_other_bin", False),
                ))
            else:
                compiled_bins.append(ScoringBin(
                    bin_id=bid,
                    woe=float(wv),
                    kind="categorical",
                    categories=tuple(be.get("categories", [])),
                    is_missing=be.get("is_missing_bin", False),
                    is_other=be.get("is_other_bin", False),
                ))

        # Determine unmatched fallback policy from bin structure and feature contract.
        has_other = any(b.is_other for b in compiled_bins)
        if has_other:
            unmatched_policy: Literal["error", "zero"] = "zero"
        else:
            unmatched_policy = "zero" if unknown_category_policy == "zero" else "error"

        variables.append(ScoringVariable(
            name=var,
            coefficient=coef,
            missing_policy=missing_policy,
            unmatched_policy=unmatched_policy,
            bins=tuple(compiled_bins),
        ))

    return variables


def compute_log_odds_and_direction(
    scorecard_dict: dict[str, Any],
    model_dict: dict[str, Any],
) -> tuple[float, float, float, float]:
    """Extract score values shared by all renderers."""
    intercept = float(model_dict.get("intercept", 0))
    offset = float(scorecard_dict.get("offset", 0))
    factor_val = float(scorecard_dict.get("factor", 1))
    higher_is_lower = (
        scorecard_dict.get("score_direction", "higher_is_lower_risk")
        == "higher_is_lower_risk"
    )
    direction = -1.0 if higher_is_lower else 1.0
    return intercept, offset, factor_val, direction
