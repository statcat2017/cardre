from __future__ import annotations

from typing import Any

import polars as pl

from cardre.nodes.build._bin_counts import make_bin_counts


def bin_categorical(
    df: pl.DataFrame, col: str, target_column: str,
    good_values: set[str], bad_values: set[str],
    max_categorical_levels: int, warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build categorical bins for a single column."""
    # Count non-null distinct values
    non_null = df.filter(pl.col(col).is_not_null())
    null_count = df.height - non_null.height

    if non_null.height == 0:
        warnings.append({
            "variable": col, "code": "ALL_NULL_CATEGORICAL",
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

    # Count frequencies per category
    value_counts = (
        non_null.group_by(col)
        .agg([pl.len().alias("_count")])
        .sort("_count", descending=True)
    )
    top_categories = value_counts[col].to_list()[:max_categorical_levels]
    other_categories = value_counts[col].to_list()[max_categorical_levels:]

    bins: list[dict[str, Any]] = []
    bin_counter = 0

    for cat in top_categories:
        bin_counter += 1
        bin_df = df.filter(pl.col(col) == cat)
        bc = make_bin_counts(bin_df, col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": str(cat),
            "lower": None,
            "upper": None,
            "lower_inclusive": False,
            "upper_inclusive": False,
            "categories": [str(cat)],
            "is_missing_bin": False,
            "is_other_bin": False,
            **bc,
        })

    # Other bucket
    if other_categories:
        bin_counter += 1
        other_vals = list(other_categories)
        mask = pl.col(col).is_in(other_vals) if len(other_vals) > 0 else pl.lit(False)
        bin_df = df.filter(mask)
        bc = make_bin_counts(bin_df, col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}",
            "label": "Other",
            "lower": None,
            "upper": None,
            "lower_inclusive": False,
            "upper_inclusive": False,
            "categories": [str(v) for v in other_categories],
            "is_missing_bin": False,
            "is_other_bin": True,
            **bc,
        })

    # Missing bin
    if null_count > 0:
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

    return bins
