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
