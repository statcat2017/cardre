"""Manual-binning preview — pure functions extracted from manual_binning_service.

WOE convention: uses ``BAD_OVER_GOOD`` (ln(bad_pct / good_pct)) so that
positive WOE = higher risk, which is more intuitive in the editor.
"""
from __future__ import annotations

from typing import Any

from cardre.engine.binning.woe import WoeConvention, compute_iv, compute_woe


def extract_woe_by_bin(variable_data: dict[str, Any]) -> list[dict[str, Any]]:
    bins = variable_data.get("bins", [])
    total_good = sum(b.get("good_count", 0) or 0 for b in bins)
    total_bad = sum(b.get("bad_count", 0) or 0 for b in bins)

    results: list[dict[str, Any]] = []
    for b in bins:
        good_count = b.get("good_count", 0) or 0
        bad_count = b.get("bad_count", 0) or 0
        row_count = b.get("row_count", 0) or 0

        good_pct = good_count / total_good if total_good > 0 else 0.0
        bad_pct = bad_count / total_bad if total_bad > 0 else 0.0

        if good_pct <= 0:
            woe = -10.0
        elif bad_pct <= 0:
            woe = 10.0
        else:
            woe = compute_woe(good_pct, bad_pct, WoeConvention.BAD_OVER_GOOD)

        results.append({
            "bin_id": b.get("bin_id", ""),
            "label": b.get("label", ""),
            "good_count": good_count,
            "bad_count": bad_count,
            "row_count": row_count,
            "good_pct": round(good_pct, 6),
            "bad_pct": round(bad_pct, 6),
            "woe": round(woe, 6),
        })

    return results


def extract_iv(variable_data: dict[str, Any]) -> float:
    bins = variable_data.get("bins", [])
    total_good = sum(b.get("good_count", 0) or 0 for b in bins)
    total_bad = sum(b.get("bad_count", 0) or 0 for b in bins)
    return round(compute_iv(bins, total_good, total_bad, WoeConvention.BAD_OVER_GOOD), 6)


def extract_event_rate_by_bin(variable_data: dict[str, Any]) -> list[dict[str, Any]]:
    bins = variable_data.get("bins", [])
    results: list[dict[str, Any]] = []
    for b in bins:
        row_count = b.get("row_count", 0) or 0
        bad_count = b.get("bad_count", 0) or 0
        event_rate = bad_count / row_count if row_count > 0 else 0.0
        results.append({
            "bin_id": b.get("bin_id", ""),
            "label": b.get("label", ""),
            "row_count": row_count,
            "event_count": bad_count,
            "event_rate": round(event_rate, 6),
        })
    return results


__all__ = [
    "extract_event_rate_by_bin",
    "extract_iv",
    "extract_woe_by_bin",
]
