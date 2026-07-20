from __future__ import annotations

from typing import Any

import polars as pl

from cardre.nodes.build._bin_counts import make_bin_counts


def bin_numeric(
    df: pl.DataFrame, col: str, target_column: str,
    good_values: set[str], bad_values: set[str],
    max_bins: int, min_bin_fraction: float,
    missing_policy: str, warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    non_null = df.filter(pl.col(col).is_not_null())
    missing = df.filter(pl.col(col).is_null())

    good_list = list(good_values)
    bad_list = list(bad_values)

    bins: list[dict[str, Any]] = []
    bin_counter = 0

    if missing.height > 0 and missing_policy == "separate_bin":
        bin_counter += 1
        mb = make_bin_counts(missing, col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": "Missing",
            "lower": None, "upper": None,
            "lower_inclusive": False, "upper_inclusive": False,
            "categories": None, "is_missing_bin": True,
            "row_count": mb["row_count"], "good_count": mb["good_count"], "bad_count": mb["bad_count"],
        })

    if non_null.height == 0:
        return bins

    n = non_null.height
    n_bins = min(max_bins, n)
    pre_count = 1 if missing.height > 0 and missing_policy == "separate_bin" else 0
    max_non_missing = max_bins - pre_count

    if max_non_missing <= 0:
        return bins

    actual_n_bins = min(n_bins, max_non_missing)

    binned = non_null.with_columns([
        pl.col(col).qcut(actual_n_bins, allow_duplicates=True, include_breaks=True).alias("_qcut_bin"),
        pl.col(target_column).cast(pl.String).alias("_tgt_str"),
    ])

    bin_stats = binned.with_columns([
        binned["_qcut_bin"].struct.field("breakpoint").alias("_brk"),
    ]).group_by("_brk", maintain_order=True).agg([
        pl.len().alias("row_count"),
        pl.col("_tgt_str").is_in(bad_list).sum().alias("bad_count"),
        pl.col("_tgt_str").is_in(good_list).sum().alias("good_count"),
    ]).sort("_brk")

    _all_bk = bin_stats["_brk"].to_list()

    for i, rec in enumerate(bin_stats.to_dicts()):
        bin_counter += 1
        brk = rec["_brk"]
        row_count = rec["row_count"]
        bad_count = rec["bad_count"]
        good_count = rec["good_count"]

        is_last = i == len(bin_stats) - 1
        hi = None if brk == float("inf") else float(brk)
        if i == 0:
            lo = None
            lower_inc = False
        else:
            lower_inc = False
            lo = float(_all_bk[i - 1]) if _all_bk[i - 1] != float("inf") else None

        if lo is not None and hi is not None:
            label = f"({lo:.4g}, {hi:.4g}]"
        elif lo is not None:
            label = f"({lo:.4g}, +inf)"
        elif hi is not None:
            label = f"(-inf, {hi:.4g}]"
        else:
            label = "All values"

        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": label,
            "lower": lo,
            "upper": hi,
            "lower_inclusive": lower_inc,
            "upper_inclusive": not is_last,
            "categories": None,
            "is_missing_bin": False,
            "row_count": row_count,
            "good_count": good_count,
            "bad_count": bad_count,
        })

        if row_count / n < min_bin_fraction:
            warnings.append({
                "variable": col, "bin_id": bins[-1]["bin_id"],
                "message": f"Bin fraction {row_count / n:.4f} is below min_bin_fraction {min_bin_fraction}",
            })

    if bin_counter == 0 and non_null.height > 0:
        bc = make_bin_counts(df.filter(pl.col(col).is_not_null()), col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": "All values",
            "lower": None, "upper": None,
            "lower_inclusive": False, "upper_inclusive": True,
            "categories": None, "is_missing_bin": False,
            "row_count": bc["row_count"], "good_count": bc["good_count"], "bad_count": bc["bad_count"],
        })

    return bins
