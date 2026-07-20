from __future__ import annotations

import polars as pl


def make_bin_counts(
    bin_df: pl.DataFrame, col: str, target_column: str,
    good_values: set[str], bad_values: set[str],
) -> dict[str, int]:
    row_count = bin_df.height
    if target_column and target_column in bin_df.columns and (good_values or bad_values):
        target_series = bin_df[target_column].cast(pl.String)
        good_count = int(target_series.is_in(list(good_values)).sum()) if good_values else 0
        bad_count = int(target_series.is_in(list(bad_values)).sum()) if bad_values else 0
    else:
        good_count = 0
        bad_count = 0
    return {"row_count": row_count, "good_count": good_count, "bad_count": bad_count}
