"""Canonical WOE application — strict failure invariant tests.

Pins the canonical apply-woe behaviour: a bin without a WOE value is a
strict failure (raise). There is no permissive fallback policy.
"""

from __future__ import annotations

import polars as pl
import pytest

from cardre.domain.binning.woe import apply_woe_columns


def _var_defs():
    return [
        {
            "variable": "age",
            "kind": "numeric",
            "bins": [
                {"bin_id": "b1", "lower": None, "upper": 30, "upper_inclusive": True},
                {"bin_id": "b2", "lower": 30, "lower_inclusive": False, "upper": None},
            ],
        },
        {
            "variable": "region",
            "kind": "categorical",
            "bins": [
                {"bin_id": "c1", "categories": ["north", "south"]},
                {"bin_id": "c2", "categories": ["east", "west"]},
            ],
        },
    ]


def _frame() -> pl.DataFrame:
    return pl.DataFrame({
        "age": [20, 40, 25, 50],
        "region": ["north", "east", "south", "west"],
    })


def _full_woe(var: str, bid: str):
    table = {
        "age": {"b1": 0.5, "b2": -0.3},
        "region": {"c1": 0.2, "c2": -0.1},
    }
    return table.get(var, {}).get(bid)


def test_apply_woe_matches_validate_apply_behavior() -> None:
    df, cols = apply_woe_columns(
        _frame(), _var_defs(), _full_woe,
    )
    assert cols == ["age_woe", "region_woe"]
    assert df["age_woe"].to_list() == [0.5, -0.3, 0.5, -0.3]
    assert df["region_woe"].to_list() == [0.2, -0.1, 0.2, -0.1]


def test_missing_woe_raises() -> None:
    with pytest.raises(ValueError, match="missing WOE for age:b1"):
        apply_woe_columns(
            _frame(), _var_defs(),
            lambda var, bid: None if (var, bid) == ("age", "b1") else _full_woe(var, bid),
        )


def test_unknown_variable_skipped() -> None:
    df, cols = apply_woe_columns(
        _frame(), _var_defs() + [{"variable": "missing_col", "kind": "numeric", "bins": []}],
        _full_woe,
    )
    assert cols == ["age_woe", "region_woe"]


def test_variable_without_bins_raises() -> None:
    with pytest.raises(ValueError, match="variable 'age' has no bins defined"):
        apply_woe_columns(
            _frame(),
            [{"variable": "age", "kind": "numeric", "bins": []}],
            _full_woe,
        )


def test_skip_missing_variable_false_absent_column_raises() -> None:
    """With skip_missing_variable=False, an absent column with a missing WOE
    is a strict failure (no permissive fallback)."""
    with pytest.raises(ValueError, match="missing WOE"):
        apply_woe_columns(
            _frame(),
            [{"variable": "missing_col", "kind": "numeric",
              "bins": [{"bin_id": "b1", "lower": None, "upper": 10}]}],
            _full_woe, skip_missing_variable=False,
        )
