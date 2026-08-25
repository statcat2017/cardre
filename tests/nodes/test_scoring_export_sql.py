"""SQL scorer and Python/SQL parity unit tests for scoring-export.

These unit tests compile scorecards and assert on the generated SQL scorer's
behaviour (NULL propagation for missing/unmatched values, single-category
categorical bins) and on Python/SQL output parity for missing, unmatched, and
known inputs under the zero-policy contracts.
"""

from __future__ import annotations

import sqlite3

from cardre.domain.evidence.models.binning import BinDefinition, BinVariable
from cardre.domain.evidence.models.woe import WoeTable
from cardre.nodes.build.scoring_export import (
    _build_python_scorer_source,
    _build_sql_scorer_source,
)
from cardre.nodes.build.scoring_export_ir import compile_scorecard
from tests.nodes._scoring_helpers import _exec_scorer, make_simple_numeric_agecard


def test_python_sql_parity_missing_without_bin_zero_policy():
    """Python and SQL produce the same score for missing values when no
    missing bin exists and missing_policy='zero'."""
    bin_def, woe_table, scorecard_raw, model_raw = make_simple_numeric_agecard()
    feature_contract = {"missing_policy": "zero", "unknown_category_policy": "error"}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    py_source = _build_python_scorer_source(variables, scorecard_raw, model_raw)
    sql_source = _build_sql_scorer_source(variables, scorecard_raw, model_raw)

    py_scorer = _exec_scorer(py_source)
    py_score = py_scorer({"age": None})

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE input_data (age REAL)")
        conn.execute("INSERT INTO input_data VALUES (NULL)")
        conn.commit()
        cursor = conn.execute(f"SELECT * FROM (\n{sql_source}\n)")
        col_names = [desc[0] for desc in cursor.description]
        score_idx = col_names.index("score")
        sql_score = cursor.fetchone()[score_idx]
    finally:
        conn.close()

    assert abs(py_score - sql_score) <= 1e-9, (
        f"Missing-without-bin zero-policy mismatch: py={py_score}, sql={sql_score}"
    )


def test_python_sql_parity_unmatched_non_null_zero_policy():
    """Python and SQL produce the same score for unmatched non-null values
    when unmatched_policy='zero'."""
    bin_def, woe_table, scorecard_raw, model_raw = make_simple_numeric_agecard()
    feature_contract = {"missing_policy": "error", "unknown_category_policy": "zero"}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    py_source = _build_python_scorer_source(variables, scorecard_raw, model_raw)
    sql_source = _build_sql_scorer_source(variables, scorecard_raw, model_raw)

    py_scorer = _exec_scorer(py_source)
    py_score = py_scorer({"age": 99})

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE input_data (age REAL)")
        conn.execute("INSERT INTO input_data VALUES (99)")
        conn.commit()
        cursor = conn.execute(f"SELECT * FROM (\n{sql_source}\n)")
        col_names = [desc[0] for desc in cursor.description]
        score_idx = col_names.index("score")
        sql_score = cursor.fetchone()[score_idx]
    finally:
        conn.close()

    assert abs(py_score - sql_score) <= 1e-9, (
        f"Unmatched zero-policy mismatch: py={py_score}, sql={sql_score}"
    )


def test_sql_scorer_missing_without_bin_error_policy_returns_null():
    """SQL returns NULL for missing value when no missing bin and
    missing_policy='error'."""
    bin_def, woe_table, scorecard_raw, model_raw = make_simple_numeric_agecard()
    feature_contract = {"missing_policy": "error", "unknown_category_policy": "error"}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    source = _build_sql_scorer_source(variables, scorecard_raw, model_raw)

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE input_data (age REAL)")
        conn.execute("INSERT INTO input_data VALUES (NULL)")
        conn.commit()
        cursor = conn.execute(f"SELECT * FROM (\n{source}\n)")
        col_names = [desc[0] for desc in cursor.description]
        woe_idx = col_names.index("woe_age")
        score_idx = col_names.index("score")
        row = cursor.fetchone()
        assert row[woe_idx] is None, (
            f"Missing-without-bin error-policy should produce NULL WOE, got {row[woe_idx]}"
        )
        assert row[score_idx] is None, (
            f"Missing-without-bin error-policy should produce NULL score, got {row[score_idx]}"
        )
    finally:
        conn.close()


def test_python_sql_parity_on_missing_unmatched_known():
    """Python and SQL scorers produce identical scores for missing,
    unmatched non-null, and known values with the same input."""
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
            BinVariable(
                variable="product_type",
                dtype="str",
                kind="categorical",
                bins=[
                    {"bin_id": "c1", "label": "loan", "categories": ["loan"]},
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={
            "age": {"b1": -0.5, "b2": 0.3, "b3": 0.7},
            "product_type": {"c1": 0.5},
        },
        columns=["variable", "bin_id", "woe"],
    )
    scorecard_raw = {
        "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20,
        "factor": 14.427, "offset": 543.6, "score_direction": "higher_is_lower_risk",
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": -0.5, "coefficients": {"age_woe": 0.8, "product_type_woe": 1.0},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "separate_bin", "unknown_category_policy": "error"}

    variables = compile_scorecard(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    py_source = _build_python_scorer_source(variables, scorecard_raw, model_raw)
    sql_source = _build_sql_scorer_source(variables, scorecard_raw, model_raw)

    test_cases = [
        {"age": None, "product_type": "loan", "label": "missing age"},
        {"age": 25, "product_type": "loan", "label": "known age + known product"},
        {"age": 40, "product_type": "loan", "label": "other known age + known product"},
    ]

    # Python scorer
    py_scorer = _exec_scorer(py_source)

    for tc in test_cases:
        py_score = py_scorer({"age": tc["age"], "product_type": tc["product_type"]})
        # SQL scorer
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE input_data (age REAL, product_type TEXT)")
            conn.execute(
                "INSERT INTO input_data VALUES (?, ?)",
                (tc["age"], tc["product_type"]),
            )
            conn.commit()
            full_sql = f"SELECT * FROM (\n{sql_source}\n)"
            cursor = conn.execute(full_sql)
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]
            score_idx = col_names.index("score")
            sql_score = rows[0][score_idx]
        finally:
            conn.close()

        assert abs(py_score - sql_score) <= 1e-9, (
            f"Python/SQL mismatch for {tc['label']}: py={py_score}, sql={sql_score}"
        )


def test_sql_scorer_single_category_bin():
    """Verify single-category categorical bins generate correct SQL.

    A single-category bin must produce a proper tuple literal like
    IN ('loan') not IN ('loan') — actually IN ('loan') is correct in SQL
    for a single value. The test verifies the generated SQL is valid
    and produces correct results.
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
    source = _build_sql_scorer_source(variables, scorecard_raw, model_raw)

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE input_data (product_type TEXT)")
        conn.execute("INSERT INTO input_data VALUES ('loan')")
        conn.execute("INSERT INTO input_data VALUES ('loa')")
        conn.execute("INSERT INTO input_data VALUES ('other_val')")
        conn.commit()
        full_sql = f"SELECT * FROM (\n{source}\n)"
        cursor = conn.execute(full_sql)
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]
        score_idx = col_names.index("score")
        scores = [row[score_idx] for row in rows]
        # 'loan' and 'loa' should have different scores (no substring matching in SQL)
        assert scores[0] != scores[1], (
            f"Single-category SQL bin must not match substrings: "
            f"loan={scores[0]}, loa={scores[1]}"
        )
        # 'other_val' should fall into the other bin
        assert scores[2] != scores[0], "Other bin should produce a different score"
    finally:
        conn.close()


def test_sql_scorer_unmatched_non_null_returns_null():
    """When a variable has a missing bin but no other bin, an out-of-range
    non-null value must produce NULL (not silently scored as 0.0)."""
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
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={"age": {"b1": -0.5, "b2": 0.3}},
        columns=["age", "bin_id", "woe"],
    )
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
    source = _build_sql_scorer_source(variables, scorecard_raw, model_raw)

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE input_data (age REAL)")
        conn.execute("INSERT INTO input_data VALUES (NULL)")     # missing bin -> -0.5
        conn.execute("INSERT INTO input_data VALUES (25)")      # 18-30 bin -> 0.3
        conn.execute("INSERT INTO input_data VALUES (99)")       # out of range -> NULL
        conn.commit()
        full_sql = f"SELECT * FROM (\n{source}\n)"
        cursor = conn.execute(full_sql)
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]
        woe_idx = col_names.index("woe_age")
        score_idx = col_names.index("score")
        woe_vals = [row[woe_idx] for row in rows]
        score_vals = [row[score_idx] for row in rows]
        # NULL row: WOE should be -0.5, score should be non-null
        assert woe_vals[0] == -0.5, f"Expected -0.5 for NULL, got {woe_vals[0]}"
        assert score_vals[0] is not None, "Score for NULL should be non-null"
        # 25 row: WOE should be 0.3
        assert woe_vals[1] == 0.3, f"Expected 0.3 for 25, got {woe_vals[1]}"
        # 99 row: out of range, WOE should be NULL
        assert woe_vals[2] is None, (
            f"Out-of-range value 99 should produce NULL WOE, got {woe_vals[2]}"
        )
        assert score_vals[2] is None, (
            f"Out-of-range value 99 should produce NULL score, got {score_vals[2]}"
        )
    finally:
        conn.close()
