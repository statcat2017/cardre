"""Shared bin-mask construction for WOE and apply nodes."""

from __future__ import annotations

from typing import Any

import polars as pl


def build_bin_condition(
    bin_def: dict,
    col_ref: pl.Series | pl.Expr,
    kind: str,
    all_bins: list[dict] | None = None,
) -> pl.Series | pl.Expr:
    is_missing = bin_def.get("is_missing_bin", False)

    if kind == "numeric":
        return _build_numeric_mask(bin_def, col_ref, is_missing)
    return _build_categorical_mask(bin_def, col_ref, is_missing, all_bins or [])


def _build_numeric_mask(
    bin_def: dict,
    col_ref: pl.Series | pl.Expr,
    is_missing: bool,
) -> pl.Series | pl.Expr:
    lower = bin_def.get("lower")
    upper = bin_def.get("upper")
    lower_inc = bin_def.get("lower_inclusive", False)
    upper_inc = bin_def.get("upper_inclusive", True)

    if is_missing:
        return col_ref.is_null()

    parts: list[Any] = []
    if lower is not None:
        parts.append((col_ref >= lower) if lower_inc else (col_ref > lower))
    if upper is not None:
        parts.append((col_ref <= upper) if upper_inc else (col_ref < upper))
    if not parts:
        raise ValueError("Numeric bin has no lower or upper boundary")

    result = parts[0]
    for p in parts[1:]:
        result = result & p
    return result


def _build_categorical_mask(
    bin_def: dict,
    col_ref: pl.Series | pl.Expr,
    is_missing: bool,
    all_bins: list[dict],
) -> pl.Series | pl.Expr:
    categories = bin_def.get("categories", [])

    if is_missing:
        return col_ref.is_null()
    if bin_def.get("is_other_bin", False):
        explicit: list[str | int | float] = []
        for ob in all_bins:
            if ob.get("is_missing_bin", False) or ob.get("is_other_bin", False):
                continue
            explicit.extend(ob.get("categories") or [])
        return col_ref.is_not_null() & ~col_ref.is_in(explicit)
    if categories:
        return col_ref.is_in(categories)

    return col_ref.is_null() & col_ref.is_not_null()
