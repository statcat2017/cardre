"""OptBinning adapter — supervised bin discovery for Cardre.

This module wraps optbinning's OptimalBinning (per-variable) and converts
its output to Cardre's SCHEMA_BIN_DEFINITION format.

Does not use optbinning's Scorecard class. Does not use BinningProcess.
One OptimalBinning object per variable for granular control.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import version as _get_version
from typing import Any

import polars as pl


@dataclass(frozen=True)
class VariableBinningResult:
    variable: str
    dtype: str
    status: str       # "OPTIMAL", "FEASIBLE", "INFEASIBLE", "FAILED"
    bins: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    metrics: dict[str, Any] = field(default_factory=dict)
    splits: list[Any] = field(default_factory=list)
    raw_engine_payload: dict[str, Any] | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class AdapterResult:
    engine_name: str = "optbinning"
    engine_version: str = ""
    variables: list[VariableBinningResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def fit_variables(
    df: pl.DataFrame,
    target: str,
    good_values: set[str],
    bad_values: set[str],
    variable_names: list[str],
    variable_types: dict[str, str],
    special_codes: dict[str, list[Any]] | None = None,
    params: dict[str, Any] | None = None,
) -> AdapterResult:
    """Fit optimal binning per variable. Converts output to Cardre bin dicts.

    Returns AdapterResult with per-variable bins conforming to
    SCHEMA_BIN_DEFINITION and a manifest with engine metadata.

    Raises nothing — failures are captured per-variable in result.status.
    """
    from optbinning import OptimalBinning

    if params is None:
        params = {}
    if special_codes is None:
        special_codes = {}

    # Target conversion: bad/event → 1, good/non-event → 0
    target_series = df[target].cast(pl.String)
    y = pl.Series("target", [
        1 if str(v) in bad_values else 0 if str(v) in good_values else None
        for v in target_series.to_list()
    ])
    if y.null_count() > 0:
        raise ValueError(
            f"Target column '{target}' contains values outside good_values "
            f"and bad_values. Found {y.null_count()} unknown value(s)."
        )
    y_np = y.to_numpy().astype(int)

    results: list[VariableBinningResult] = []
    warnings: list[str] = []

    for variable in variable_names:
        x = df[variable].to_numpy()
        dtype = variable_types[variable]
        var_params = _build_params(variable, dtype, special_codes, params)

        optb = OptimalBinning(**var_params)
        try:
            optb.fit(x, y_np)
            bins = _extract_bins(variable, dtype, optb)
            metrics = _extract_variable_metrics(variable, bins, optb)
            splits = list(optb.splits) if hasattr(optb, 'splits') else []
            raw_engine_payload = _safe_to_dict(optb)
            results.append(VariableBinningResult(
                variable=variable, dtype=dtype,
                status=_resolve_status(optb),
                bins=bins, warnings=[], metrics=metrics,
                splits=splits, raw_engine_payload=raw_engine_payload,
            ))
        except Exception as exc:
            warnings.append(f"{variable}: optbinning failed: {exc}")
            results.append(VariableBinningResult(
                variable=variable, dtype=dtype,
                status="FAILED", bins=[], warnings=[{"code": "VARIABLE_FAILED", "severity": "error", "variable": variable, "message": str(exc)}],
                failure_reason=str(exc),
            ))

    try:
        engine_version = _get_version("optbinning")
    except Exception:
        engine_version = "unknown"

    succeeded = [r.variable for r in results if r.status in ("OPTIMAL", "FEASIBLE")]
    failed = [r.variable for r in results if r.status == "FAILED"]
    total_warnings = sum(len(r.warnings) for r in results)
    manifest = {
        "engine": "optbinning",
        "engine_version": engine_version,
        "parameters": params,
        "variable_count": len(variable_names),
        "variables_succeeded": len(succeeded),
        "variables_failed": len(failed),
        "succeeded": succeeded,
        "failed": failed,
        "warnings_count": total_warnings,
    }

    return AdapterResult(
        engine_version=engine_version,
        variables=results,
        warnings=warnings,
        manifest=manifest,
    )


def _resolve_status(optb) -> str:
    """Map optbinning status to a stable string."""
    raw = getattr(optb, "status", "")
    # optbinning returns None when it hasn't been fit
    if raw is None:
        return "FAILED"
    s = str(raw).upper()
    if s in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "FAILED"):
        return s
    return s


def _build_params(
    variable: str,
    dtype: str,
    special_codes: dict[str, list[Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    p: dict[str, Any] = {
        "name": variable,
        "dtype": dtype,
        "prebinning_method": params.get("prebinning_method", "cart"),
        "solver": params.get("solver", "cp"),
        "divergence": params.get("divergence", "iv"),
        "max_n_prebins": int(params.get("max_n_prebins", 20)),
        "min_prebin_size": float(params.get("min_prebin_size", 0.05)),
        "max_n_bins": int(params.get("max_n_bins", 6)),
        "min_bin_size": float(params.get("min_bin_size", 0.03)),
        "min_bin_n_event": int(params.get("min_bin_n_event", 20)),
        "min_bin_n_nonevent": int(params.get("min_bin_n_nonevent", 20)),
        "monotonic_trend": params.get("monotonic_trend", "auto"),
        "time_limit": int(params.get("time_limit", 100)),
        "verbose": False,
    }
    if "min_n_bins" in params and params["min_n_bins"] is not None:
        p["min_n_bins"] = int(params["min_n_bins"])
    if dtype == "categorical":
        p["cat_cutoff"] = float(params.get("cat_cutoff", 0.01))
        if "cat_unknown" in params:
            p["cat_unknown"] = params["cat_unknown"]
    if variable in special_codes:
        p["special_codes"] = special_codes[variable]
    return p


def _extract_bins(
    variable: str,
    dtype: str,
    optb,
) -> list[dict[str, Any]]:
    """Convert optbinning output to Cardre SCHEMA_BIN_DEFINITION bin dicts
    with rich per-bin metrics (WOE, IV, bad_rate, row_pct)."""
    table = optb.binning_table.build()
    splits = list(optb.splits) if hasattr(optb, 'splits') else []

    bins: list[dict[str, Any]] = []
    table_bin_idx = 0
    regular_numeric_idx = 0
    total_count = 0

    # First pass: count total rows for row_pct
    for _, row in table.iterrows():
        label = str(row.get("Bin", ""))
        if label.lower().startswith("totals"):
            continue
        total_count += int(row.get("Count", 0))

    for _, row in table.iterrows():
        label = str(row.get("Bin", ""))
        if label.lower().startswith("totals"):
            continue

        table_bin_idx += 1
        count = int(row.get("Count", 0))
        event = int(row.get("Event", 0))
        nonevent = int(row.get("Non-event", 0))

        is_missing = _is_missing_bin(row)
        is_special = _is_special_bin(row, optb)

        bad_rate = float(row.get("Event rate", 0)) if "Event rate" in row else (event / count if count > 0 else None)
        woe = float(row.get("WoE", 0)) if "WoE" in row else None
        iv = float(row.get("IV", 0)) if "IV" in row else None
        row_pct = count / total_count if total_count > 0 else 0.0

        bin_dict: dict[str, Any] = {
            "bin_id": f"{variable}_bin_{table_bin_idx:03d}",
            "label": _clean_label(label),
            "kind": dtype,
            "lower": None,
            "upper": None,
            "lower_inclusive": False,
            "upper_inclusive": False,
            "categories": None,
            "is_missing_bin": is_missing,
            "row_count": count,
            "row_pct": row_pct,
            "good_count": nonevent,
            "bad_count": event,
            "bad_rate": bad_rate,
            "woe": woe,
            "iv": iv,
        }

        if is_special:
            bin_dict["is_special_bin"] = True
            sc = getattr(optb, 'special_codes', [])
            if sc is not None:
                bin_dict["special_values"] = list(sc)

        is_regular_numeric = dtype in ("numeric", "numerical") and not is_missing and not is_special
        if is_regular_numeric and splits:
            regular_numeric_idx += 1
            _assign_numeric_bounds(bin_dict, regular_numeric_idx, splits)

        elif not is_regular_numeric and dtype == "categorical" and not is_missing:
            cats = _extract_categories(label)
            if cats:
                bin_dict["categories"] = cats

        bins.append(bin_dict)

    return bins


def _extract_variable_metrics(
    variable: str,
    bins: list[dict[str, Any]],
    optb,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "n_bins": len(bins),
        "row_count": sum(b.get("row_count", 0) for b in bins),
        "missing_count": sum(b.get("row_count", 0) for b in bins if b.get("is_missing_bin")),
    }
    iv_vals = [b.get("iv") for b in bins if b.get("iv") is not None]
    if iv_vals:
        metrics["iv"] = sum(iv_vals)
    non_missing = [b for b in bins if not b.get("is_missing_bin")]
    if non_missing:
        metrics["min_bin_count"] = min(b.get("row_count", 0) for b in non_missing)
        metrics["max_bin_pct"] = max(b.get("row_pct", 0) for b in non_missing)
    missing_count = metrics.get("missing_count", 0)
    total = metrics.get("row_count", 0) or 1
    metrics["missing_rate"] = missing_count / total
    woe_vals = [b.get("woe") for b in bins if b.get("woe") is not None and not b.get("is_missing_bin") and not b.get("is_special_bin")]
    if len(woe_vals) >= 2:
        increasing = all(woe_vals[i] <= woe_vals[i + 1] for i in range(len(woe_vals) - 1))
        decreasing = all(woe_vals[i] >= woe_vals[i + 1] for i in range(len(woe_vals) - 1))
        metrics["monotonic_woe"] = increasing or decreasing
    return metrics


def _safe_to_dict(optb) -> dict[str, Any] | None:
    try:
        return optb.to_dict()
    except Exception:
        return None


def _assign_numeric_bounds(
    bin_dict: dict[str, Any],
    bin_idx: int,
    splits: list,
) -> None:
    n_splits = len(splits)
    if n_splits == 0:
        bin_dict["label"] = "All values"
    elif bin_idx == 1:
        bin_dict["lower"] = None
        bin_dict["upper"] = float(splits[0])
        bin_dict["label"] = f"(-inf, {float(splits[0]):g})"
        bin_dict["lower_inclusive"] = False
        bin_dict["upper_inclusive"] = False
    elif bin_idx == n_splits + 1:
        bin_dict["lower"] = float(splits[-1])
        bin_dict["upper"] = None
        bin_dict["label"] = f"[{float(splits[-1]):g}, +inf)"
        bin_dict["lower_inclusive"] = True
        bin_dict["upper_inclusive"] = False
    else:
        lo = float(splits[bin_idx - 2])
        hi = float(splits[bin_idx - 1])
        bin_dict["lower"] = lo
        bin_dict["upper"] = hi
        bin_dict["label"] = f"[{lo:g}, {hi:g})"
        bin_dict["lower_inclusive"] = True
        bin_dict["upper_inclusive"] = False


def _is_missing_bin(row) -> bool:
    bin_val = str(row.get("Bin", "")).strip().lower()
    return bin_val in ("missing",)


def _is_special_bin(row, optb) -> bool:
    sc = getattr(optb, 'special_codes', [])
    if not sc:
        return False
    label = str(row.get("Bin", ""))
    if not label:
        return False
    # Match special code as a delimited token — prevents 99 matching in 199/999.
    import re
    for code in sc:
        pattern = rf"(?<![-\d]){re.escape(str(code))}(?![-\d])"
        if re.search(pattern, label):
            return True
    return False


def _clean_label(label: str) -> str:
    return label.strip()


def _extract_categories(label: str) -> list[str] | None:
    """Extract category list from optbinning's categorical bin label."""
    if not label:
        return None
    label_stripped = label.strip()
    if label_stripped.lower() in ("missing", "nan", "null", "special"):
        return None
    parts = [p.strip() for p in label_stripped.split(",") if p.strip()]
    return parts if parts else [label_stripped]
