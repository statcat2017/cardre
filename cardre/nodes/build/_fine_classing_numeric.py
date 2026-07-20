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
    bad_list = list(bad_values)

    non_null = df.filter(pl.col(col).is_not_null())
    null_count = df.height - non_null.height

    bins: list[dict[str, Any]] = []

    if non_null.height == 0:
        warnings.append({
            "variable": col, "code": "ALL_NULL",
            "message": f"Column {col!r} is entirely null; assigning a singleton missing bin.",
        })
        bc = make_bin_counts(df, col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_001",
            "label": "Missing",
            "lower": None, "upper": None,
            "lower_inclusive": False, "upper_inclusive": False,
            "categories": [], "is_missing_bin": True, "is_other_bin": False,
            **bc,
        })
        return bins

    n = non_null.height
    n_bins = min(max_bins, n)
    pre_count = 1 if null_count > 0 and missing_policy == "separate_bin" else 0
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
    ])

    bin_counter = 0
    for i in range(len(bin_stats)):
        brk = bin_stats["_brk"][i]
        rc = bin_stats["row_count"][i]
        bc = bin_stats["bad_count"][i]
        gc = rc - bc

        bin_counter += 1
        lower = bin_stats["_brk"][i - 1] if i > 0 else float("-inf")
        upper = brk

        if rc / n < min_bin_fraction and actual_n_bins > 2:
            warnings.append({
                "variable": col, "code": "SPARSE_BIN",
                "message": f"Bin {lower:.4f}–{upper:.4f} has {rc} rows "
                           f"({rc / n:.1%}), below min_bin_fraction {min_bin_fraction:.0%}.",
            })

        is_first = i == 0
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": f"[{lower:.4f}, {upper:.4f}]",
            "upper": round(float(upper), 6),
            "lower": round(float(lower), 6),
            "lower_inclusive": is_first,
            "upper_inclusive": True,
            "categories": [],
            "is_missing_bin": False,
            "is_other_bin": False,
            "row_count": rc,
            "good_count": gc,
            "bad_count": int(bc),
        })

    if null_count > 0 and missing_policy == "separate_bin":
        bin_counter += 1
        mb = make_bin_counts(df.filter(pl.col(col).is_null()), col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": "Missing",
            "lower": None, "upper": None,
            "lower_inclusive": False, "upper_inclusive": False,
            "categories": [], "is_missing_bin": True, "is_other_bin": False,
            **mb,
        })
    elif null_count > 0:
        warnings.append({
            "variable": col, "code": "MISSING_IGNORED",
            "message": f"Column {col!r} has {null_count} null(s) and missing_policy is 'ignore'.",
        })

    return bins
