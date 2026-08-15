"""Canonical WOE application — policy parity tests.

Pins the three historical missing-WOE policies that previously lived in
three separate copy-pasted loops (validate/apply.py, build/features.py,
build/clustering.py) into one canonical function.
"""

from __future__ import annotations

import polars as pl
import pytest

from cardre.engine.binning.woe import MissingWoePolicy, apply_woe_columns


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


def test_raise_policy_matches_validate_apply_behavior() -> None:
    df, cols = apply_woe_columns(
        _frame(), _var_defs(), _full_woe, policy=MissingWoePolicy.RAISE,
    )
    assert cols == ["age_woe", "region_woe"]
    assert df["age_woe"].to_list() == [0.5, -0.3, 0.5, -0.3]
    assert df["region_woe"].to_list() == [0.2, -0.1, 0.2, -0.1]


def test_raise_policy_missing_woe_raises() -> None:
    with pytest.raises(ValueError, match="missing WOE for age:b1"):
        apply_woe_columns(
            _frame(), _var_defs(),
            lambda var, bid: None if (var, bid) == ("age", "b1") else _full_woe(var, bid),
            policy=MissingWoePolicy.RAISE,
        )


def test_zero_policy_matches_features_transform() -> None:
    df, cols = apply_woe_columns(
        _frame(), _var_defs(),
        lambda var, bid: None if (var, bid) == ("age", "b1") else _full_woe(var, bid),
        policy=MissingWoePolicy.ZERO,
    )
    assert cols == ["age_woe", "region_woe"]
    assert df["age_woe"].to_list() == [0.0, -0.3, 0.0, -0.3]


def test_zero_policy_no_bins_raises() -> None:
    with pytest.raises(ValueError, match="has no bins defined"):
        apply_woe_columns(
            _frame(), [{"variable": "age", "kind": "numeric", "bins": []}],
            _full_woe, policy=MissingWoePolicy.ZERO,
        )


def test_skip_bin_policy_matches_clustering_preview() -> None:
    df, cols = apply_woe_columns(
        _frame(), _var_defs(),
        lambda var, bid: None if (var, bid) == ("age", "b1") else _full_woe(var, bid),
        policy=MissingWoePolicy.SKIP_BIN,
    )
    assert cols == ["age_woe", "region_woe"]
    # b1 omitted from the chain: rows in b1 get null, others get b2's WOE
    assert df["age_woe"].to_list() == [None, -0.3, None, -0.3]


def test_unknown_variable_skipped() -> None:
    df, cols = apply_woe_columns(
        _frame(), _var_defs() + [{"variable": "missing_col", "kind": "numeric", "bins": []}],
        _full_woe, policy=MissingWoePolicy.RAISE,
    )
    assert cols == ["age_woe", "region_woe"]


def test_skip_missing_variable_false_raises_on_absent_column() -> None:
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        apply_woe_columns(
            _frame(),
            [{"variable": "missing_col", "kind": "numeric",
              "bins": [{"bin_id": "b1", "lower": None, "upper": 10}]}],
            _full_woe, policy=MissingWoePolicy.ZERO, skip_missing_variable=False,
        )
