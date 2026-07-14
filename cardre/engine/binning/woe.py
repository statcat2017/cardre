"""WOE/IV calculation — canonical implementation.

Centralises the duplicated WOE calculation logic that was previously
inline in cardre/nodes/build/features.py and
cardre/services/manual_binning_service.py.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any


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
