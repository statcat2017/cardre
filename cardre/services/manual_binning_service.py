"""Manual-binning preview and validation — pure functions extracted from v1.

These functions operate on evidence data to extract WOE/IV/event-rate
metrics for the manual-binning editor preview panel.
"""

from __future__ import annotations

import math
from typing import Any


def extract_woe_by_bin(variable_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract Weight of Evidence (WOE) per bin from a variable's bin data.

    Expected input structure (from binning evidence artifact)::

        {
            "variable": "income",
            "kind": "numeric",
            "bins": [
                {
                    "bin_id": "...",
                    "label": "Low",
                    "good_count": 100,
                    "bad_count": 50,
                    "row_count": 150,
                    ...
                },
                ...
            ]
        }

    Returns a list of dicts, one per bin, with keys:
        bin_id, label, good_count, bad_count, row_count,
        good_pct, bad_pct, woe

    WOE is defined as: ln(bad_pct / good_pct)
    A small epsilon is added to avoid division by zero.
    """
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

        # WOE = ln(bad_pct / good_pct); clip to avoid log(0)
        if good_pct <= 0:
            woe = -10.0  # large negative WOE when no goods
        elif bad_pct <= 0:
            woe = 10.0   # large positive WOE when no bads
        else:
            woe = math.log(bad_pct / good_pct)

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
    """Extract Information Value (IV) from a variable's bin data.

    IV = sum over bins of (bad_pct - good_pct) * WOE
    """
    woe_by_bin = extract_woe_by_bin(variable_data)
    iv = 0.0
    for entry in woe_by_bin:
        iv += (entry["bad_pct"] - entry["good_pct"]) * entry["woe"]
    return round(iv, 6)


def extract_event_rate_by_bin(variable_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract event rate (bad count / row count) per bin.

    Returns a list of dicts with keys:
        bin_id, label, row_count, event_count, event_rate
    """
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
