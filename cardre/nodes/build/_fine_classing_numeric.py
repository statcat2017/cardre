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
    """Build equal-frequency numeric bins for a single column."""
    non_null = df.filter(pl.col(col).is_not_null())
    null_count = df.height - non_null.height

    if non_null.height == 0:
        warnings.append({
            "variable": col, "code": "ALL_NULL",
            "message": f"Column {col!r} is entirely null; assigning a singleton missing bin.",
        })
        bc = make_bin_counts(df, col, target_column, good_values, bad_values)
        return [{
            "bin_id": f"{col}_bin_001",
            "label": "Missing",
            "lower": None,
            "upper": None,
            "lower_inclusive": False,
            "upper_inclusive": False,
            "categories": [],
            "is_missing_bin": True,
            "is_other_bin": False,
            **bc,
        }]

    col_vals = non_null[col]
    n = non_null.height

    # Determine number of bins
    target_bins = min(max_bins, n)
    if target_bins < 2:
        target_bins = 2

    # Equal-frequency bin edges using polars quantiles
    quantiles = [i / target_bins for i in range(target_bins + 1)]
    # Handle duplicated quantile boundaries
    edges: list[float] = []
    for q in quantiles:
        v = col_vals.quantile(q, interpolation="linear")
        if v is not None:
            fv = round(float(v), 6)
            if not edges or abs(fv - edges[-1]) > 1e-12:
                edges.append(fv)

    while len(edges) < 2 and n > 1:
        mx = col_vals.max()
        if mx is not None:
            edges.append(float(mx))  # type: ignore[arg-type]

    bins: list[dict[str, Any]] = []
    bin_counter = 0

    for i in range(len(edges) - 1):
        lower = edges[i]
        upper = edges[i + 1]
        if i == 0:
            mask = pl.col(col) >= lower
        else:
            mask = pl.col(col) > lower
        mask = mask & (pl.col(col) <= upper)

        bin_df = df.filter(mask)
        rc = bin_df.height
        if rc == 0:
            continue
        bc = make_bin_counts(bin_df, col, target_column, good_values, bad_values)
        if rc / n < min_bin_fraction and target_bins > 2:
            warnings.append({
                "variable": col, "code": "SPARSE_BIN",
                "message": f"Bin {lower:.4f}–{upper:.4f} has {rc} rows "
                           f"({rc / n:.1%}), below min_bin_fraction {min_bin_fraction:.0%}.",
            })

        bin_counter += 1
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": f"[{lower:.4f}, {upper:.4f}]",
            "upper": round(upper, 6),
            "lower": round(lower, 6),
            "lower_inclusive": i == 0,
            "upper_inclusive": True,
            "categories": [],
            "is_missing_bin": False,
            "is_other_bin": False,
            **bc,
        })

    # Missing bin
    if null_count > 0:
        if missing_policy == "separate_bin":
            bin_counter += 1
            bc = make_bin_counts(df.filter(pl.col(col).is_null()), col, target_column, good_values, bad_values)
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}",
                "label": "Missing",
                "lower": None,
                "upper": None,
                "lower_inclusive": False,
                "upper_inclusive": False,
                "categories": [],
                "is_missing_bin": True,
                "is_other_bin": False,
                **bc,
            })
        else:
            warnings.append({
                "variable": col, "code": "MISSING_IGNORED",
                "message": f"Column {col!r} has {null_count} null(s) and missing_policy is 'ignore'.",
            })

    return bins
