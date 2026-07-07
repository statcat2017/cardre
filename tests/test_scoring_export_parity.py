"""Parity tests: exported Python and SQL scorers match apply-model output.

Runs the full canonical scorecard workflow, then compares scores from the
generated Python scorer and SQL scorer against the apply-model reference
output for every row in train/test/oot.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

import polars as pl

from cardre._evidence.schemas import SCHEMA_SCORING_EXPORT_PYTHON, SCHEMA_SCORING_EXPORT_SQL
from cardre.workflows import build_canonical_scorecard_steps


def _write_input_csv(path: Path) -> Path:
    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_scoring_export_parity(raw_project_path, api_client, tmp_path):
    project_dir = tmp_path / "parity.cardre"
    resp = api_client.post("/projects", json={"name": "Parity", "path": str(project_dir)})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]
    headers = {"X-Project-Path": str(project_dir)}

    csv_path = _write_input_csv(tmp_path / "input.csv")

    resp = api_client.post(
        f"/projects/{project_id}/plans",
        headers=headers,
        json={"name": "Parity Plan"},
    )
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["plan_id"]

    from cardre.store.db import ProjectStore
    from cardre.store.plan_repo import PlanRepository
    store = ProjectStore(project_dir)
    store.open()
    try:
        steps = build_canonical_scorecard_steps(csv_path)
        plan_version_id = PlanRepository(store).create_version(
            plan_id, steps=steps, is_committed=True,
        )
    finally:
        store.close()

    resp = api_client.post(
        f"/projects/{project_id}/runs",
        headers=headers,
        json={"plan_version_id": plan_version_id, "sync": True, "force": True},
    )
    assert resp.status_code == 201, resp.text
    run_data = resp.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "succeeded", f"Run did not succeed: {run_data}"

    store = ProjectStore(project_dir)
    store.open()
    try:
        artifact_rows = store.execute(
            """SELECT a.artifact_id, a.role, a.path, a.metadata_json, rs.step_id
               FROM artifacts a
               JOIN artifact_lineage al ON al.artifact_id = a.artifact_id
               JOIN run_steps rs ON rs.run_step_id = al.run_step_id
               WHERE rs.run_id = ? AND al.direction = 'output'""",
            (run_id,),
        ).fetchall()

        apply_model_parquet = [
            row for row in artifact_rows
            if row["step_id"] == "apply-model" and row["role"] in {"train", "test"}
        ]
        assert len(apply_model_parquet) >= 2, "apply-model should produce train + test parquet"

        python_export = [
            row for row in artifact_rows
            if row["step_id"] == "scoring-export-python"
            and f'"schema_version": "{SCHEMA_SCORING_EXPORT_PYTHON}"' in row["metadata_json"]
        ]
        assert python_export, "scoring-export-python artifact not found"
        python_payload = json.loads(
            (store.root / python_export[0]["path"]).read_text(encoding="utf-8")
        )
        python_source = python_payload["source"]

        sql_export = [
            row for row in artifact_rows
            if row["step_id"] == "scoring-export-sql"
            and f'"schema_version": "{SCHEMA_SCORING_EXPORT_SQL}"' in row["metadata_json"]
        ]
        assert sql_export, "scoring-export-sql artifact not found"
        sql_payload = json.loads(
            (store.root / sql_export[0]["path"]).read_text(encoding="utf-8")
        )
        sql_source = sql_payload["source"]

        for row in apply_model_parquet:
            role = row["role"]
            df = pl.read_parquet(store.root / row["path"])
            assert "score" in df.columns, f"apply-model {role} missing score column"

            ref_scores = df["score"].to_list()
            records = df.drop(["score", "cardre_scaled_score", "predicted_bad_probability",
                               "raw_model_output", "model_artifact_id", "model_family"]).to_dicts()

            # Python parity
            local_ns: dict[str, Any] = {}
            exec(python_source, local_ns)
            scorer = local_ns["score_cardre"]
            py_scores = [scorer(rec) for rec in records]
            for i, (ref, py) in enumerate(zip(ref_scores, py_scores, strict=True)):
                assert abs(ref - py) <= 1e-9, (
                    f"Python scorer mismatch at {role}[{i}]: ref={ref}, py={py}"
                )

            # SQL parity
            conn = sqlite3.connect(":memory:")
            try:
                conn.execute("CREATE TABLE input_data (credit_amount REAL, age_years REAL, duration_months REAL, credit_risk_class TEXT)")
                for rec in records:
                    conn.execute(
                        "INSERT INTO input_data VALUES (?, ?, ?, ?)",
                        (rec["credit_amount"], rec["age_years"], rec["duration_months"], rec["credit_risk_class"]),
                    )
                conn.commit()
                full_sql = f"SELECT * FROM (\n{sql_source}\n)"
                cursor = conn.execute(full_sql)
                sql_rows = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description]
                score_idx = col_names.index("score")
                sql_scores = [row[score_idx] for row in sql_rows]
                assert len(sql_scores) == len(ref_scores), (
                    f"SQL scorer returned {len(sql_scores)} rows, expected {len(ref_scores)}"
                )
                for i, (ref, sql_val) in enumerate(zip(ref_scores, sql_scores, strict=True)):
                    assert abs(ref - sql_val) <= 1e-9, (
                        f"SQL scorer mismatch at {role}[{i}]: ref={ref}, sql={sql_val}"
                    )
            finally:
                conn.close()

    finally:
        store.close()


def test_python_scorer_missing_value_handling():
    """Verify the generated Python scorer handles missing bins correctly.

    Builds a synthetic bin definition with a missing bin, generates the
    scorer source, and checks that a None input maps to the missing-bin WOE
    rather than 0.0.
    """
    from cardre._evidence.models.binning import BinDefinition, BinVariable
    from cardre._evidence.models.woe import WoeTable
    from cardre.nodes.build.scoring_export import _build_python_scorer_source

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
        "factor": 14.427, "offset": 543.6, "higher_score_is_lower_risk": True,
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": -0.5, "coefficients": {"age_woe": 0.8},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "separate_bin", "unknown_category_policy": "error"}

    source = _build_python_scorer_source(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    local_ns: dict[str, Any] = {}
    exec(source, local_ns)
    scorer = local_ns["score_cardre"]

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
    from cardre._evidence.models.binning import BinDefinition, BinVariable
    from cardre._evidence.models.woe import WoeTable
    from cardre.nodes.build.scoring_export import _build_python_scorer_source

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
        "factor": 14.427, "offset": 543.6, "higher_score_is_lower_risk": True,
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": 0.0, "coefficients": {"product_type_woe": 1.0},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "error", "unknown_category_policy": "error"}

    source = _build_python_scorer_source(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    local_ns: dict[str, Any] = {}
    exec(source, local_ns)
    scorer = local_ns["score_cardre"]

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
    from cardre._evidence.models.binning import BinDefinition, BinVariable
    from cardre._evidence.models.woe import WoeTable
    from cardre.nodes.build.scoring_export import _build_python_scorer_source

    bin_def = BinDefinition(
        source_artifact_id="test",
        variables=[
            BinVariable(
                variable="age",
                dtype="int64",
                kind="numeric",
                bins=[
                    {"bin_id": "b1", "label": "18-30", "lower": 18, "upper": 30, "lower_inclusive": True, "upper_inclusive": True},
                ],
            ),
        ],
    )
    woe_table = WoeTable(
        mapping={"age": {"b1": 0.3}},
        columns=["age", "bin_id", "woe"],
    )
    scorecard_raw = {
        "base_score": 600, "base_odds": 50.0, "points_to_double_odds": 20,
        "factor": 14.427, "offset": 543.6, "higher_score_is_lower_risk": True,
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": 0.0, "coefficients": {"age_woe": 1.0},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "error", "unknown_category_policy": "error"}

    source = _build_python_scorer_source(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)
    local_ns: dict[str, Any] = {}
    exec(source, local_ns)
    scorer = local_ns["score_cardre"]

    import pytest
    with pytest.raises(ValueError, match="missing value for age"):
        scorer({"age": None})


def test_sql_scorer_single_category_bin():
    """Verify single-category categorical bins generate correct SQL.

    A single-category bin must produce a proper tuple literal like
    IN ('loan') not IN ('loan') — actually IN ('loan') is correct in SQL
    for a single value. The test verifies the generated SQL is valid
    and produces correct results.
    """
    from cardre._evidence.models.binning import BinDefinition, BinVariable
    from cardre._evidence.models.woe import WoeTable
    from cardre.nodes.build.scoring_export import _build_sql_scorer_source

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
        "factor": 14.427, "offset": 543.6, "higher_score_is_lower_risk": True,
        "base_points": 543.6, "attributes": [],
    }
    model_raw = {
        "intercept": 0.0, "coefficients": {"product_type_woe": 1.0},
        "model_family": "logistic_regression",
    }
    feature_contract = {"missing_policy": "error", "unknown_category_policy": "error"}

    source = _build_sql_scorer_source(bin_def, woe_table, scorecard_raw, model_raw, feature_contract)

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
