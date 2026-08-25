"""Generated Python scorer unit tests for scoring-export.

These unit tests compile a scorecard to a Python scorer source via
``scoring_export_ir.compile_scorecard`` + ``_build_python_scorer_source``,
exec it, and assert on the generated scorer's behaviour: missing-bin handling,
single-category categorical bins, missing-without-bin error policy, and
unmatched numeric/categorical values raising ``ValueError``.
"""

from __future__ import annotations

import pytest

from cardre.domain.evidence.models.binning import BinDefinition, BinVariable
from cardre.domain.evidence.models.woe import WoeTable
from cardre.nodes.build.scoring_export import _build_python_scorer_source
from cardre.nodes.build.scoring_export_ir import compile_scorecard
from tests.nodes._scoring_helpers import _exec_scorer, make_simple_numeric_agecard


def test_python_scorer_missing_value_handling():
    """Verify the generated Python scorer handles missing bins correctly.

    Builds a synthetic bin definition with a missing bin, generates the
    scorer source, and checks that a None input maps to the missing-bin WOE
    rather than 0.0.
    """
    bin_def = BinDefinition(
        source_artifact_id="test",
        variables=[
            BinVariable(
                variable="age",
                dtype="int64",
                kind="numeric",
                bins=[
                    {"bin_id": "b1", "label": "missing", "is_missing_bin": True},
                    {"bin_id": "b2", "label": "18-30", "lower": 18, "upper": 30, "lower_inclusive": True, "upper_inclusive": True},
                    {"bin_id": "b3", "label": "31+", "lower": 31, "upper_inclusive": True, "lower_inclusive": True},
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={"age": {"b1": -0.5, "b2": 0.3, "b3": 0.7}},
        columns=["age", "bin_id", "woe"],
    )
    scorecard_raw = {
        "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20,
        "factor": 14.427, "offset": 543.6, "score_direction": "higher_is_lower_risk",
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": -0.5, "coefficients": {"age_woe": 0.8},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "separate_bin", "unknown_category_policy": "error"}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    scorer = _exec_scorer(_build_python_scorer_source(variables, scorecard_raw, model_raw))

    # Missing value should use missing-bin WOE (-0.5), not 0.0
    score_missing = scorer({"age": None})
    score_known = scorer({"age": 25})
    assert score_missing != score_known, "Missing and known values should produce different scores"
    # Verify the missing-bin WOE is actually used by computing expected
    intercept = -0.5
    coef = 0.8
    offset = 543.6
    factor = 14.427
    direction = -1.0
    expected_missing = offset + direction * factor * (intercept + coef * (-0.5))
    assert abs(score_missing - expected_missing) <= 1e-9, (
        f"Missing value score {score_missing} != expected {expected_missing}"
    )


def test_python_scorer_single_category_bin():
    """Verify single-category categorical bins generate correct Python.

    A single-category bin must produce a proper tuple literal, not a
    parenthesized string that triggers substring matching.
    """
    bin_def = BinDefinition(
        source_artifact_id="test",
        variables=[
            BinVariable(
                variable="product_type",
                dtype="str",
                kind="categorical",
                bins=[
                    {"bin_id": "b1", "label": "loan", "categories": ["loan"]},
                    {"bin_id": "b2", "label": "other", "is_other_bin": True},
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={"product_type": {"b1": 0.5, "b2": -0.3}},
        columns=["product_type", "bin_id", "woe"],
    )
    scorecard_raw = {
        "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20,
        "factor": 14.427, "offset": 543.6, "score_direction": "higher_is_lower_risk",
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": 0.0, "coefficients": {"product_type_woe": 1.0},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "error", "unknown_category_policy": "error"}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    scorer = _exec_scorer(_build_python_scorer_source(variables, scorecard_raw, model_raw))

    # "loan" should match the single-category bin
    score_loan = scorer({"product_type": "loan"})
    # "loa" should NOT match (substring trap)
    score_loa = scorer({"product_type": "loa"})
    assert score_loan != score_loa, (
        "Single-category bin must not match substrings: 'loa' should not match 'loan'"
    )

    # "other_val" should fall into the other bin
    score_other = scorer({"product_type": "other_val"})
    assert score_other != score_loan, "Other bin should produce a different score"


def test_python_scorer_missing_value_no_missing_bin():
    """When no missing bin exists and policy is 'error', the scorer must raise."""
    bin_def, woe_table, scorecard_raw, model_raw = make_simple_numeric_agecard()
    scorecard_raw = {
        "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20,
        "factor": 14.427, "offset": 543.6, "score_direction": "higher_is_lower_risk",
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": 0.0, "coefficients": {"age_woe": 1.0},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "error", "unknown_category_policy": "error"}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    scorer = _exec_scorer(_build_python_scorer_source(variables, scorecard_raw, model_raw))

    with pytest.raises(ValueError, match="missing value for age"):
        scorer({"age": None})


def test_python_unmatched_numeric_raises():
    """An out-of-range numeric value raises ValueError in the Python scorer,
    matching the SQL ELSE NULL behavior (error propagation)."""
    bin_def, woe_table, scorecard_raw, model_raw = make_simple_numeric_agecard()

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw)
    scorer = _exec_scorer(_build_python_scorer_source(variables, scorecard_raw, model_raw))

    with pytest.raises(ValueError, match="unmatched value for age"):
        scorer({"age": 99})


def test_python_unmatched_categorical_raises():
    """An unknown category raises ValueError in the Python scorer,
    matching the SQL ELSE NULL behavior."""
    bin_def = BinDefinition(
        source_artifact_id="test",
        variables=[
            BinVariable(
                variable="product_type", dtype="str", kind="categorical",
                bins=[
                    {"bin_id": "c1", "label": "loan", "categories": ["loan"]},
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={"product_type": {"c1": 0.5}},
        columns=["variable", "bin_id", "woe"],
    )
    scorecard_raw = {"factor": 1, "offset": 0, "score_direction": "higher_is_lower_risk"}
    model_raw = {"intercept": 0.0, "coefficients": {"product_type_woe": 1.0}}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw)
    scorer = _exec_scorer(_build_python_scorer_source(variables, scorecard_raw, model_raw))

    with pytest.raises(ValueError, match="unmatched value for product_type"):
        scorer({"product_type": "unknown_category"})
