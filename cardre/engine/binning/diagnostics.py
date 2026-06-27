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


class MonotonicStatus(str, enum.Enum):
    monotonic = "monotonic"
    non_monotonic = "non_monotonic"
    insufficient_bins = "insufficient_bins"


def check_sparse_bins_ratio(
    bins: list[dict],
    threshold: float = 0.05,
) -> bool:
    """Return True if any bin holds fewer than `threshold` of total rows."""
    if not bins:
        return False
    total = sum(b.get("count", 0) for b in bins)
    if total == 0:
        return False
    return any(b.get("count", 0) / total < threshold for b in bins)


def check_sparse_bins_ratio_count(
    bins: list[dict],
    threshold: float = 0.05,
) -> int:
    """Count bins below the sparse threshold."""
    if not bins:
        return 0
    total = sum(b.get("count", 0) for b in bins)
    if total == 0:
        return 0
    return sum(1 for b in bins if b.get("count", 0) / total < threshold)


def check_zero_cell_bins(bins: list[dict]) -> int:
    """Count bins where good_count == 0 or bad_count == 0."""
    count = 0
    for b in bins:
        if b.get("good_count") == 0 or b.get("bad_count") == 0:
            count += 1
    return count


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


def check_solver_status(
    status: str,
    variable: str = "",
) -> list[BinningDiagnostic]:
    """Warn if solver status is not OPTIMAL."""
    if not status or status.upper() not in ("OPTIMAL", "FEASIBLE"):
        return [
            BinningDiagnostic(
                code="SOLVER_NOT_OPTIMAL",
                severity="warning",
                variable=variable,
                message=f"Solver status: {status}",
                details={"status": status},
            )
        ]
    if status.upper() == "FEASIBLE":
        return [
            BinningDiagnostic(
                code="SOLVER_NOT_OPTIMAL",
                severity="info",
                variable=variable,
                message=f"Solver reached FEASIBLE (not OPTIMAL): {status}",
                details={"status": status},
            )
        ]
    return []


def check_too_few_bins(
    bins: list[dict],
    variable: str = "",
    min_bins: int = 2,
) -> list[BinningDiagnostic]:
    """Warn if fewer than min_bins bins were produced."""
    if len(bins) < min_bins:
        return [
            BinningDiagnostic(
                code="TOO_FEW_BINS",
                severity="warning",
                variable=variable,
                message=f"Only {len(bins)} bin(s) found (minimum: {min_bins})",
                details={"bin_count": len(bins), "min_bins": min_bins},
            )
        ]
    return []


def check_sparse_bins(
    bins: list[dict],
    variable: str = "",
    min_count: int = 30,
) -> list[BinningDiagnostic]:
    """Warn if any bin has fewer than min_count total rows."""
    results: list[BinningDiagnostic] = []
    for b in bins:
        count = b.get("row_count", 0)
        if count < min_count:
            bid = b.get("bin_id", "")
            results.append(
                BinningDiagnostic(
                    code="SPARSE_BIN",
                    severity="warning",
                    variable=variable or b.get("variable"),
                    bin_id=bid,
                    message=f"Bin '{b.get('label', bid)}' has {count} rows (minimum: {min_count})",
                    requires_acknowledgement=True,
                    details={
                        "bin_id": bid,
                        "row_count": count,
                        "min_count": min_count,
                    },
                )
            )
    return results


def check_pure_bins(
    variable: str,
    bins: list[dict],
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


def check_variable_failed(
    variable: str,
    status: str,
    warnings: list | None = None,
) -> list[BinningDiagnostic]:
    """Variable failed during optbinning fit."""
    if status == "FAILED":
        warning_msgs = []
        if warnings:
            for w in warnings:
                if isinstance(w, dict):
                    warning_msgs.append(w.get("message", str(w)))
                else:
                    warning_msgs.append(str(w))
        return [
            BinningDiagnostic(
                code="VARIABLE_FAILED",
                severity="error",
                variable=variable,
                message=f"Variable failed: {'; '.join(warning_msgs)}" if warning_msgs else "Variable failed",
                requires_acknowledgement=True,
                details={"status": status, "warnings": warnings or []},
            )
        ]
    return []


def run_all(
    variable_results: list,
    min_bins: int = 2,
    min_bin_count: int = 30,
) -> list[BinningDiagnostic]:
    """Run all fit-time diagnostics on a list of VariableBinningResult objects."""
    all_diags: list[BinningDiagnostic] = []
    for vr in variable_results:
        variable = vr.variable
        status = vr.status if hasattr(vr, 'status') else ""
        bins = vr.bins if hasattr(vr, 'bins') else []

        all_diags.extend(check_variable_failed(variable, status, getattr(vr, 'warnings', [])))
        all_diags.extend(check_solver_status(status, variable))
        all_diags.extend(check_too_few_bins(bins, variable, min_bins))
        all_diags.extend(check_sparse_bins(bins, variable, min_bin_count))

    return all_diags
