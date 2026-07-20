from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from cardre.domain.diagnostics import JsonDict


def derive_binary_target(
    frame: pl.DataFrame,
    target_column: str,
    good_values: set[str],
    bad_values: set[str],
) -> tuple[np.ndarray | None, np.ndarray | None, list[JsonDict]]:
    warnings: list[JsonDict] = []
    if not target_column or target_column not in frame.columns:
        warnings.append({
            "code": "MISSING_TARGET_COLUMN",
            "message": f"Target column {target_column!r} not found; "
                       "all metrics except row count are unavailable.",
        })
        return None, None, warnings
    if not good_values and not bad_values:
        warnings.append({
            "code": "MISSING_TARGET_METADATA",
            "message": "No good_values/bad_values in definition artifact; "
                       "all metrics except row count are unavailable.",
        })
        return None, None, warnings

    good_list = list(good_values)
    bad_list = list(bad_values)
    all_known = good_values | bad_values
    target_str = frame[target_column].cast(pl.String)
    known_mask = target_str.is_in(all_known).to_numpy()
    unknown_count = int((~known_mask).sum())
    if unknown_count > 0:
        warnings.append({
            "code": "UNKNOWN_TARGET_VALUES",
            "message": f"Target column {target_column!r} contains {unknown_count} row(s) "
                       f"with values not declared as good or bad. "
                       f"These rows are excluded from metric computation.",
        })

    y_bin_full: np.ndarray[Any, Any] = frame.with_columns(
        pl.when(target_str.is_in(bad_list))
        .then(pl.lit(1))
        .when(target_str.is_in(good_list))
        .then(pl.lit(0))
        .otherwise(pl.lit(None))
        .alias("_y_binary")
    )["_y_binary"].drop_nulls().to_numpy().astype(np.int64)

    n_bad = int(y_bin_full.sum()) if len(y_bin_full) > 0 else 0
    n_good = int(len(y_bin_full) - n_bad) if len(y_bin_full) > 0 else 0
    if n_bad == 0 and n_good == 0:
        warnings.append({
            "code": "NO_KNOWN_TARGET_VALUES",
            "message": f"Target column {target_column!r} has no rows with declared good or bad values; "
                       "all metrics are unavailable.",
        })
        return None, None, warnings
    if n_bad == 0:
        warnings.append({
            "code": "SINGLE_CLASS_ONLY_GOOD",
            "message": f"Target column {target_column!r} has no bad-class rows; "
                       "AUC and discrimination metrics are undefined.",
        })
    elif n_good == 0:
        warnings.append({
            "code": "SINGLE_CLASS_ONLY_BAD",
            "message": f"Target column {target_column!r} has no good-class rows; "
                       "AUC and discrimination metrics are undefined.",
        })
    return y_bin_full, known_mask, warnings


def calibration_summary(
    frame: pl.DataFrame, target_column: str, bad_list: list[str], n_bins: int = 10,
) -> JsonDict:
    calib: JsonDict = {}
    try:
        from sklearn.calibration import calibration_curve

        all_str = frame[target_column].cast(pl.String)
        y_true = frame.with_columns(
            pl.when(all_str.is_in(bad_list)).then(1).otherwise(0).alias("_y_calib")
        )["_y_calib"].to_numpy()
        y_prob = frame["predicted_bad_probability"].to_numpy()

        if len(y_true) < n_bins:
            return {"note": f"Too few rows ({len(y_true)}) for calibration."}

        prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="quantile")
        calib = {
            "prob_true": [float(v) for v in prob_true],
            "prob_pred": [float(v) for v in prob_pred],
            "n_bins": n_bins,
            "strategy": "quantile",
        }
    except Exception:
        calib = {"note": "Calibration computation failed."}
    return calib


def score_distribution(scores: np.ndarray) -> JsonDict:
    if len(scores) == 0:
        return {}
    return {
        "min": round(float(scores.min()), 6),
        "max": round(float(scores.max()), 6),
        "mean": round(float(scores.mean()), 6),
        "median": round(float(np.median(scores)), 6),
        "std": round(float(scores.std()), 6),
        "p1": round(float(np.percentile(scores, 1)), 6),
        "p5": round(float(np.percentile(scores, 5)), 6),
        "p25": round(float(np.percentile(scores, 25)), 6),
        "p75": round(float(np.percentile(scores, 75)), 6),
        "p95": round(float(np.percentile(scores, 95)), 6),
        "p99": round(float(np.percentile(scores, 99)), 6),
        "n": int(len(scores)),
    }


def population_stability_index(
    expected: pl.Series, actual: pl.Series, n_bins: int = 10,
) -> tuple[float, list[JsonDict]]:
    import numpy as np

    psi_warnings: list[JsonDict] = []
    if expected.is_empty() or actual.is_empty():
        return 0.0, psi_warnings

    expected_arr = expected.to_numpy()
    actual_arr = actual.to_numpy()
    bin_edges = np.percentile(expected_arr, [i * 100 / n_bins for i in range(1, n_bins)])
    bin_edges = np.unique(bin_edges)
    if len(bin_edges) <= 1:
        expected_counts = np.array([len(expected_arr)])
        actual_counts = np.array([len(actual_arr)])
    else:
        extended_edges = np.concatenate([[-np.inf], bin_edges, [np.inf]])
        expected_counts = np.histogram(expected_arr, bins=extended_edges)[0]
        actual_counts = np.histogram(actual_arr, bins=extended_edges)[0]

    psi = 0.0
    n_exp = len(expected_arr)
    n_act = len(actual_arr)
    for bin_idx, (ec, ac) in enumerate(zip(expected_counts, actual_counts, strict=False)):
        ep = ec / n_exp
        ap = ac / n_act
        if ap == 0 or ep == 0:
            if ep == 0:
                ep = 0.5 / n_exp
            if ap == 0:
                ap = 0.5 / n_act
            psi_warnings.append({
                "code": "PSI_EMPTY_BIN",
                "bin_index": bin_idx,
                "message": f"Bin {bin_idx} had zero count; floored for PSI computation",
            })
        psi += (ap - ep) * np.log(ap / ep)
    return round(float(psi), 6), psi_warnings
