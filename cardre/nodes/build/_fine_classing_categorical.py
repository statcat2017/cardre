from __future__ import annotations

from typing import Any

import polars as pl


def bin_categorical(
    df: pl.DataFrame, col: str, target_column: str,
    good_values: set[str], bad_values: set[str],
    max_categorical_levels: int, missing_policy: str,
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    non_null = df.filter(pl.col(col).is_not_null())
    missing = df.filter(pl.col(col).is_null())

    good_list = list(good_values)
    bad_list = list(bad_values)

    bins: list[dict[str, Any]] = []
    bin_counter = 0

    if missing.height > 0 and missing_policy == "separate_bin":
        bin_counter += 1
        from cardre.nodes.build._bin_counts import make_bin_counts
        mb = make_bin_counts(missing, col, target_column, good_values, bad_values)
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}", "label": "Missing",
            "lower": None, "upper": None,
            "lower_inclusive": False, "upper_inclusive": False,
            "categories": None, "is_missing_bin": True,
            "row_count": mb["row_count"], "good_count": mb["good_count"], "bad_count": mb["bad_count"],
        })

    if non_null.height == 0:
        return bins

    vc = non_null[col].value_counts().sort("count", descending=True)
    all_levels = vc[col].to_list()

    other_categories: list[Any] = []
    if len(all_levels) > max_categorical_levels:
        other_categories = all_levels[max_categorical_levels:]
        all_levels = all_levels[:max_categorical_levels]
        warnings.append({
            "variable": col,
            "message": f"High cardinality: {len(all_levels) + len(other_categories)} categories, "
                      f"using top {max_categorical_levels} plus 'Other'",
            "dropped_categories": len(other_categories),
        })

    grouped = non_null.with_columns(
        pl.col(target_column).cast(pl.String).alias("_tgt_str"),
    ).group_by(col).agg([
        pl.len().alias("row_count"),
        pl.col("_tgt_str").is_in(bad_list).sum().alias("bad_count"),
        pl.col("_tgt_str").is_in(good_list).sum().alias("good_count"),
    ])

    level_map: dict[str, dict[str, int]] = {
        str(r[0]): {"row_count": int(r[1]), "bad_count": int(r[2]), "good_count": int(r[3])}
        for r in grouped.iter_rows()
    }

    for level in all_levels:
        key = str(level)
        stats = level_map.get(key)
        if stats is None or stats["row_count"] == 0:
            continue
        bin_counter += 1
        bad_count = stats["bad_count"]
        good_count = stats["good_count"]
        row_count = stats["row_count"]
        bins.append({
            "bin_id": f"{col}_bin_{bin_counter:03d}", "label": key,
            "lower": None, "upper": None,
            "lower_inclusive": False, "upper_inclusive": False,
            "categories": [level], "is_missing_bin": False,
            "row_count": row_count,
            "good_count": good_count,
            "bad_count": bad_count,
        })

    if other_categories:
        other_df = non_null.filter(pl.col(col).is_in(other_categories))
        if other_df.height > 0:
            other_stats = other_df.with_columns(
                pl.col(target_column).cast(pl.String).alias("_tgt_str"),
            ).select([
                pl.len().alias("row_count"),
                pl.col("_tgt_str").is_in(bad_list).sum().alias("bad_count"),
                pl.col("_tgt_str").is_in(good_list).sum().alias("good_count"),
            ])
            bin_counter += 1
            rc = other_stats["row_count"][0]
            bc = other_stats["bad_count"][0]
            gc = other_stats["good_count"][0]
            bins.append({
                "bin_id": f"{col}_bin_{bin_counter:03d}", "label": "Other",
                "lower": None, "upper": None,
                "lower_inclusive": False, "upper_inclusive": False,
                "categories": other_categories, "is_missing_bin": False, "is_other_bin": True,
                "row_count": rc,
                "good_count": gc,
                "bad_count": bc,
            })

    return bins
