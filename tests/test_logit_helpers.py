"""Direct unit tests for pure helpers in ``cardre/nodes/build/_logit_helpers.py``."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from cardre.nodes.build._logit_helpers import (
    COEF_ROUND,
    POINTS_ROUND,
    WOE_ROUND,
    build_class_mapping,
    build_lr_params,
    build_scorecard_attribute,
    parse_base_odds,
    resolve_features,
)

# ------------------------------------------------------------------
# parse_base_odds
# ------------------------------------------------------------------

class TestParseBaseOdds:

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("50:1", 50.0),
            ("50", 50.0),
            (50.0, 50.0),
            ("0:1", 0.0),
            ("1:2", 0.5),
            ("100:1", 100.0),
            ("3:4", 0.75),
            (0, 0.0),
            (600, 600.0),
        ],
    )
    def test_parses_valid_inputs(self, raw: Any, expected: float) -> None:
        assert parse_base_odds(raw) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "raw",
        [
            "abc",
            "",
            None,
            "1:0",  # division by zero
            ":",  # empty parts
            "abc:1",
            "1:def",
        ],
    )
    def test_raises_value_error_for_invalid(self, raw: Any) -> None:
        with pytest.raises(ValueError, match="base_odds must be a number or 'N:M' odds ratio string"):
            parse_base_odds(raw)


# ------------------------------------------------------------------
# build_lr_params
# ------------------------------------------------------------------

class TestBuildLrParams:

    def test_default_params(self) -> None:
        result = build_lr_params({})
        assert result == {
            "penalty": "l2",
            "C": 1.0,
            "max_iter": 1000,
            "solver": "lbfgs",
            "random_state": 42,
        }

    def test_custom_c_max_iter(self) -> None:
        result = build_lr_params({"C": 0.5, "max_iter": 500})
        assert result["C"] == 0.5
        assert result["max_iter"] == 500

    def test_custom_solver_and_penalty(self) -> None:
        result = build_lr_params({"solver": "saga", "penalty": "elasticnet"})
        assert result["solver"] == "saga"
        assert result["penalty"] == "elasticnet"

    def test_custom_random_seed(self) -> None:
        result = build_lr_params({"random_seed": 123})
        assert result["random_state"] == 123

    def test_numpy_types_are_coerced(self) -> None:
        result = build_lr_params({
            "C": np.float64(0.5),
            "max_iter": np.int64(200),
            "random_seed": np.int32(99),
        })
        assert isinstance(result["C"], float)
        assert isinstance(result["max_iter"], int)
        assert isinstance(result["random_state"], int)
        assert result["C"] == 0.5
        assert result["max_iter"] == 200
        assert result["random_state"] == 99

    def test_penalty_none_defaults_to_l2(self) -> None:
        result = build_lr_params({"penalty": None})
        assert result["penalty"] == "l2"

    def test_penalty_explicit_l1(self) -> None:
        result = build_lr_params({"penalty": "l1"})
        assert result["penalty"] == "l1"


# ------------------------------------------------------------------
# resolve_features
# ------------------------------------------------------------------

class TestResolveFeatures:

    @pytest.fixture
    def woe_cols(self) -> list[str]:
        return ["age_woe", "income_woe", "loan_amt_woe"]

    def test_with_sel_def(self, woe_cols: list[str]) -> None:
        """Returns sel_def.selected_names as source_variables."""

        class FakeSelDef:
            selected_names = {"age", "income"}

        features, sources = resolve_features(woe_cols, FakeSelDef())
        assert features == woe_cols
        assert sorted(sources) == sorted(["age", "income"])

    def test_without_sel_def_strips_suffix(self, woe_cols: list[str]) -> None:
        features, sources = resolve_features(woe_cols, None)
        assert features == woe_cols
        assert sources == ["age", "income", "loan_amt"]

    def test_empty_woe_cols(self) -> None:
        features, sources = resolve_features([], None)
        assert features == []
        assert sources == []

    def test_empty_woe_cols_with_sel_def(self) -> None:
        class FakeSelDef:
            selected_names = {"x", "y"}

        features, sources = resolve_features([], FakeSelDef())
        assert features == []
        assert sorted(sources) == sorted(["x", "y"])

    def test_sel_def_none_returns_empty_list_for_empty_features(self) -> None:
        features, sources = resolve_features([], None)
        assert features == []
        assert sources == []

    def test_non_woe_suffixed_columns_filtered_out(self) -> None:
        woe_cols = ["age_woe", "raw_col"]
        features, sources = resolve_features(woe_cols, None)
        assert features == ["age_woe", "raw_col"]
        assert sources == ["age"]  # only the one ending with _woe


# ------------------------------------------------------------------
# build_class_mapping
# ------------------------------------------------------------------

class TestBuildClassMapping:

    def test_returns_good_bad_dict(self) -> None:
        result = build_class_mapping("0", "1")
        assert result == {"good": "0", "bad": "1"}

    def test_other_labels(self) -> None:
        result = build_class_mapping("non_default", "default")
        assert result == {"good": "non_default", "bad": "default"}

    def test_preserves_identical_dict_for_both_branches(self) -> None:
        """``_behavior_preserved`` — both identical branches produce same output."""
        result_a = build_class_mapping("good_val", "bad_val")
        result_b = build_class_mapping("good_val", "bad_val")
        assert result_a == result_b
        assert result_a == {"good": "good_val", "bad": "bad_val"}


# ------------------------------------------------------------------
# build_scorecard_attribute
# ------------------------------------------------------------------

class TestBuildScorecardAttribute:

    def test_normal_values(self) -> None:
        bin_entry = {"bin_id": "b1", "label": "Age 20-30"}
        result = build_scorecard_attribute(
            variable="age",
            bin_entry=bin_entry,
            woe_val=0.5,
            coef=1.2,
            factor=28.8539,
            direction=-1.0,
        )
        assert result["variable"] == "age"
        assert result["bin_id"] == "b1"
        assert result["label"] == "Age 20-30"
        assert result["coefficient"] == 1.2
        # woe rounded to 6 places
        assert result["woe"] == 0.5
        # points = direction * factor * coef * woe = -1.0 * 28.8539 * 1.2 * 0.5 = -17.31234, rounded to 2
        expected_points = round(-1.0 * 28.8539 * 1.2 * 0.5, 2)
        assert result["points"] == expected_points

    def test_zero_woe(self) -> None:
        bin_entry = {"bin_id": "b2", "label": "Missing"}
        result = build_scorecard_attribute(
            variable="income",
            bin_entry=bin_entry,
            woe_val=0.0,
            coef=0.8,
            factor=28.8539,
            direction=-1.0,
        )
        assert result["woe"] == 0.0
        assert result["points"] == 0.0

    def test_negative_coefficient(self) -> None:
        bin_entry = {"bin_id": "b3", "label": "High risk"}
        result = build_scorecard_attribute(
            variable="loan_amt",
            bin_entry=bin_entry,
            woe_val=0.3,
            coef=-0.5,
            factor=28.8539,
            direction=-1.0,
        )
        # points = -1.0 * 28.8539 * (-0.5) * 0.3 = 4.328085, rounded to 2
        expected_points = round(-1.0 * 28.8539 * (-0.5) * 0.3, 2)
        assert result["points"] == expected_points
        assert result["coefficient"] == -0.5

    def test_positive_direction(self) -> None:
        """When higher_score_is_lower_risk=False, direction is 1.0."""
        bin_entry = {"bin_id": "b4", "label": "Some bin"}
        result = build_scorecard_attribute(
            variable="var",
            bin_entry=bin_entry,
            woe_val=0.2,
            coef=1.0,
            factor=28.8539,
            direction=1.0,
        )
        expected_points = round(1.0 * 28.8539 * 1.0 * 0.2, 2)
        assert result["points"] == expected_points

    def test_woe_rounding(self) -> None:
        """WOE is rounded to WOE_ROUND decimal places."""
        bin_entry = {"bin_id": "b5", "label": "Rounding test"}
        woe_val = 0.123456789
        result = build_scorecard_attribute(
            variable="x",
            bin_entry=bin_entry,
            woe_val=woe_val,
            coef=1.0,
            factor=1.0,
            direction=1.0,
        )
        assert result["woe"] == round(woe_val, WOE_ROUND)

    def test_points_rounding(self) -> None:
        """Points are rounded to POINTS_ROUND decimal places."""
        bin_entry = {"bin_id": "b6", "label": "Points rounding"}
        result = build_scorecard_attribute(
            variable="y",
            bin_entry=bin_entry,
            woe_val=1.0 / 3.0,
            coef=1.0,
            factor=1.0,
            direction=1.0,
        )
        expected = round(1.0 * 1.0 * 1.0 * (1.0 / 3.0), POINTS_ROUND)
        assert result["points"] == expected


# ------------------------------------------------------------------
# Module-level constants
# ------------------------------------------------------------------

class TestConstants:

    def test_woe_round_is_six(self) -> None:
        assert WOE_ROUND == 6

    def test_points_round_is_two(self) -> None:
        assert POINTS_ROUND == 2

    def test_coef_round_is_six(self) -> None:
        assert COEF_ROUND == 6
