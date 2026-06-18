"""Binning diagnostics — fit-time warning checks.

These are pure functions operating on bin dicts or adapter results.
They detect issues that can be identified immediately after fit,
before WOE computation. WOE-dependent diagnostics (non-monotonic WOE,
pure bins, etc.) belong in cardre/engine/binning/woe_diagnostics.py
and run after CalculateWoeIvNode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BinningDiagnostic:
    variable: str
    diagnostic_type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def check_solver_status(
    status: str,
    variable: str = "",
) -> list[BinningDiagnostic]:
    """Warn if solver status is not OPTIMAL."""
    if not status or status.upper() not in ("OPTIMAL", "FEASIBLE"):
        return [
            BinningDiagnostic(
                variable=variable,
                diagnostic_type="solver_not_optimal",
                message=f"Solver status: {status}",
                details={"status": status},
            )
        ]
    if status.upper() == "FEASIBLE":
        return [
            BinningDiagnostic(
                variable=variable,
                diagnostic_type="solver_feasible_not_optimal",
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
                variable=variable,
                diagnostic_type="too_few_bins",
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
            results.append(
                BinningDiagnostic(
                    variable=variable,
                    diagnostic_type="sparse_bin",
                    message=f"Bin '{b.get('label', b.get('bin_id', ''))}' has {count} rows (minimum: {min_count})",
                    details={
                        "bin_id": b.get("bin_id", ""),
                        "row_count": count,
                        "min_count": min_count,
                    },
                )
            )
    return results


def check_variable_failed(
    variable: str,
    status: str,
    warnings: list[str],
) -> list[BinningDiagnostic]:
    """Variable failed during optbinning fit."""
    if status == "FAILED":
        return [
            BinningDiagnostic(
                variable=variable,
                diagnostic_type="variable_failed",
                message=f"Variable failed: {'; '.join(warnings)}" if warnings else "Variable failed",
                details={"status": status, "warnings": warnings},
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
