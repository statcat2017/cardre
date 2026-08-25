"""Binning diagnostics — fit-time and editor-time warning checks.

These are pure functions operating on bin dicts or adapter results.
They detect issues that can be identified immediately after fit,
before WOE computation. WOE-dependent diagnostics (non-monotonic WOE,
pure bins, etc.) belong in cardre/engine/binning/woe_diagnostics.py
and run after CalculateWoeIvNode.

Editor-time diagnostics (sparse-bin ratio, monotonicity status,
blocker computation) also live here so they are the single source
of truth shared by the editor, the review gate, and evidence/report.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class MonotonicStatus(enum.StrEnum):
    monotonic = "monotonic"
    non_monotonic = "non_monotonic"
    insufficient_bins = "insufficient_bins"


def monotonicity_status(woe_by_bin: dict[str, float] | None) -> MonotonicStatus:
    """Classify WOE monotonicity across bins.

    Returns:
        MonotonicStatus.monotonic — WOE is strictly increasing or decreasing.
        MonotonicStatus.non_monotonic — WOE changes direction.
        MonotonicStatus.insufficient_bins — fewer than 3 bins with WOE.
    """
    if not woe_by_bin or len(woe_by_bin) < 3:
        return MonotonicStatus.insufficient_bins
    values = list(woe_by_bin.values())
    increasing = all(values[i] <= values[i + 1] for i in range(len(values) - 1))
    decreasing = all(values[i] >= values[i + 1] for i in range(len(values) - 1))
    if increasing or decreasing:
        return MonotonicStatus.monotonic
    return MonotonicStatus.non_monotonic


@dataclass(frozen=True)
class BinningDiagnostic:
    code: str
    severity: str          # "info" | "warning" | "error"
    variable: str | None = None
    bin_id: str | None = None
    message: str = ""
    requires_acknowledgement: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def check_pure_bins(
    variable: str,
    bins: list[dict[str, Any]],
    total_good: int,
    total_bad: int,
) -> list[BinningDiagnostic]:
    results: list[BinningDiagnostic] = []
    for b in bins:
        bin_good = b.get("good_count", 0)
        bin_bad = b.get("bad_count", 0)
        direction = None
        if bin_good > 0 and bin_bad == 0:
            direction = "all_good"
        elif bin_bad > 0 and bin_good == 0:
            direction = "all_bad"
        if direction is not None:
            results.append(BinningDiagnostic(
                code="PURE_BIN",
                severity="warning",
                variable=variable,
                bin_id=b.get("bin_id"),
                message=f"Bin {b.get('bin_id', '?')!r} of variable {variable!r} "
                       f"is a pure bin (all {direction.replace('all_', '')} rows)",
                requires_acknowledgement=True,
                details={"direction": direction, "bin_id": b.get("bin_id", "")},
            ))
    return results
