"""WOE/IV calculation — canonical implementation.

Centralises the duplicated WOE calculation logic that was previously
inline in cardre/nodes/build/features.py and
cardre/services/manual_binning_service.py.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

import polars as pl


class WoeConvention(StrEnum):
    """Which ratio is used for WOE = ln(...).

    ``GOOD_OVER_BAD``: ln(good_dist / bad_dist) — used by production WOE/IV.
    ``BAD_OVER_GOOD``: ln(bad_dist / good_dist) — used by manual-binning preview.
    """

    GOOD_OVER_BAD = "good_over_bad"
    BAD_OVER_GOOD = "bad_over_good"


def compute_woe(
    good_dist: float,
    bad_dist: float,
    convention: WoeConvention = WoeConvention.GOOD_OVER_BAD,
) -> float:
    if good_dist <= 0 or bad_dist <= 0:
        return 0.0
    if convention == WoeConvention.GOOD_OVER_BAD:
        return float(math.log(good_dist / bad_dist))
    return float(math.log(bad_dist / good_dist))


def compute_iv_component(
    good_dist: float,
    bad_dist: float,
    woe: float,
    convention: WoeConvention = WoeConvention.GOOD_OVER_BAD,
) -> float:
    if convention == WoeConvention.GOOD_OVER_BAD:
        return (good_dist - bad_dist) * woe
    return (bad_dist - good_dist) * woe


def compute_iv(
    bins: list[dict[str, Any]],
    total_good: int,
    total_bad: int,
    convention: WoeConvention = WoeConvention.GOOD_OVER_BAD,
) -> float:
    iv = 0.0
    for b in bins:
        good_count = b.get("good_count", 0) or 0
        bad_count = b.get("bad_count", 0) or 0
        good_dist = good_count / total_good if total_good > 0 else 0.0
        bad_dist = bad_count / total_bad if total_bad > 0 else 0.0
        if good_dist <= 0 or bad_dist <= 0:
            woe = -10.0 if good_dist <= 0 else 10.0
        else:
            woe = compute_woe(good_dist, bad_dist, convention)
        iv += compute_iv_component(good_dist, bad_dist, woe, convention)
    return iv


def apply_woe_columns(
    df: pl.DataFrame,
    var_defs: list[Any],
    woe_lookup: Any,
    *,
    suffix: str = "_woe",
    skip_missing_variable: bool = True,
) -> tuple[pl.DataFrame, list[str]]:
    """Apply bin definitions to *df*, adding one ``<variable><suffix>`` column per variable.

    *var_defs* are objects with ``.variable``, ``.kind`` and ``.bins`` attributes
    (or dicts with the same keys). *woe_lookup* is a callable ``(variable, bin_id) -> float | None``.

    A bin without a WOE value is a strict failure invariant: any ``None``
    returned by *woe_lookup* raises a ``ValueError``. There is no permissive
    fallback policy.

    Returns the augmented frame and the list of created column names.
    """
    from cardre.domain.binning.masks import build_bin_condition

    exprs: list[pl.Expr] = []
    created: list[str] = []

    for vd in var_defs:
        variable = vd.variable if hasattr(vd, "variable") else vd.get("variable", "")
        kind = vd.kind if hasattr(vd, "kind") else vd.get("kind", "")
        bins = vd.bins if hasattr(vd, "bins") else vd.get("bins", [])
        if skip_missing_variable and variable not in df.columns:
            continue

        woe_expr: Any | None = None
        for be in bins:
            bin_id = be["bin_id"]
            mask = build_bin_condition(be, pl.col(variable), kind, bins, variable=variable, bin_id=bin_id)
            woe_val = woe_lookup(variable, bin_id)
            if woe_val is None:
                raise ValueError(f"missing WOE for {variable}:{bin_id}")
            clause = pl.when(mask).then(pl.lit(woe_val))
            woe_expr = clause if woe_expr is None else woe_expr.when(mask).then(pl.lit(woe_val))

        if woe_expr is None:
            raise ValueError(f"WOE transform: variable {variable!r} has no bins defined")

        exprs.append(woe_expr.otherwise(pl.lit(None, dtype=pl.Float64)).alias(f"{variable}{suffix}"))
        created.append(f"{variable}{suffix}")

    if exprs:
        df = df.with_columns(exprs)
    return df, created
