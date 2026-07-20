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
    import polars as pl

    calib_df = frame.with_columns(
        pl.col("predicted_bad_probability").qcut(n_bins, allow_duplicates=True).alias("_calib_bin"),
        pl.when(pl.col(target_column).cast(pl.String).is_in(bad_list))
        .then(pl.lit(1)).otherwise(pl.lit(0)).alias("_y_binary"),
    ).group_by("_calib_bin", maintain_order=True).agg([
        pl.len().alias("count"),
        pl.col("predicted_bad_probability").mean().alias("avg_predicted_probability"),
        pl.col("_y_binary").mean().alias("actual_bad_rate"),
    ]).with_columns(
        pl.col("avg_predicted_probability").round(6),
        pl.col("actual_bad_rate").round(6),
    )

    bins: list[JsonDict] = []
    for row in calib_df.iter_rows():
        bins.append({
            "bin": len(bins),
            "count": row[1],
            "avg_predicted_probability": row[2],
            "actual_bad_rate": row[3],
        })
    return {"bins": bins}


def score_distribution(scores: np.ndarray) -> JsonDict:
    return {
        "mean": round(float(np.mean(scores)), 2),
        "median": round(float(np.median(scores)), 2),
        "min": round(float(np.min(scores)), 2),
        "max": round(float(np.max(scores)), 2),
        "std": round(float(np.std(scores)), 2),
        "p5": round(float(np.percentile(scores, 5)), 2),
        "p25": round(float(np.percentile(scores, 25)), 2),
        "p75": round(float(np.percentile(scores, 75)), 2),
        "p95": round(float(np.percentile(scores, 95)), 2),
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
