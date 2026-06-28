"""Tests for dataset-quality profiling in ProfileDatasetNode.

These are TDD red tests — they assert expected behavior before the
production code is implemented.  Each test runs ProfileDatasetNode
on a small synthetic DataFrame and checks the quality_warnings and
recommended_exclude_columns in the profile artifact payload.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

import polars as pl
import pytest

from cardre.artifacts import write_parquet_artifact
from cardre.audit import ExecutionContext, StepSpec, json_logical_hash, physical_hash, relative_path, table_logical_hash
from cardre.nodes import ProfileDatasetNode
from tests.helpers import make_store


def _profile_of(df: pl.DataFrame) -> tuple[dict, str]:
    """Run ProfileDatasetNode on *df* and return (profile_payload, artifact_id)."""
    store, tmp = make_store()
    store.create_project("test")
    art = write_parquet_artifact(
        store, artifact_type="dataset", role="input",
        stem="test-dataset", frame=df,
    )
    params = {}
    spec = StepSpec(
        step_id="profile", node_type="cardre.profile_dataset",
        node_version="1", category="transform",
        params=params, params_hash=json_logical_hash(params),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[art], validated_params=params,
        runtime_metadata={},
    )
    node = ProfileDatasetNode()
    output = node.run(ctx)
    profile_art = output.artifacts[0]
    payload = json.loads(store.artifact_path(profile_art).read_text())
    return payload, profile_art.artifact_id


# ======================================================================
# Tests
# ======================================================================


def test_profile_quality_clean_dataset_has_no_warnings() -> None:
    """A clean numeric/categorical dataset should produce no quality warnings."""
    df = pl.DataFrame({
        "customer_age": [25, 34, 45, 56, 67],
        "income": [45000.0, 62000.0, 83000.0, 72000.0, 51000.0],
        "loan_amount": [10000, 25000, 15000, 30000, 12000],
        "region": ["North", "South", "North", "South", "North"],
        "target": ["good", "bad", "good", "bad", "good"],
    })
    payload, _ = _profile_of(df)
    assert payload.get("quality_warnings", []) == [], f"Expected no warnings, got {payload.get('quality_warnings')}"
    assert payload.get("recommended_exclude_columns", []) == [], f"Expected no excludes, got {payload.get('recommended_exclude_columns')}"


def test_profile_quality_flags_suspect_columns() -> None:
    """Columns with ID/date/leakage-like names should be flagged."""
    df = pl.DataFrame({
        "customer_id": [f"C{i:04d}" for i in range(20)],
        "application_date": ["2024-01-15", "2024-02-20", "2024-03-10", "2024-04-05", "2024-05-01"] * 4,
        "default_date": [None, "2024-06-01", None, "2024-07-15", None] * 4,
        "months_since_default": [None, 3.0, None, 6.0, None] * 4,
        "income": [float(i * 1000) for i in range(20)],
        "target": ["good"] * 15 + ["bad"] * 5,
    })
    payload, _ = _profile_of(df)
    codes = {w["code"] for w in payload.get("quality_warnings", [])}
    assert "SUSPECT_ID_COLUMN" in codes, f"Expected SUSPECT_ID_COLUMN warning, got codes {codes}"
    assert "SUSPECT_DATE_COLUMN" in codes, f"Expected SUSPECT_DATE_COLUMN warning, got codes {codes}"
    assert "SUSPECT_LEAKAGE_COLUMN" in codes, f"Expected SUSPECT_LEAKAGE_COLUMN warning, got codes {codes}"
    assert "NEAR_UNIQUE_COLUMN" in codes, f"Expected NEAR_UNIQUE_COLUMN for customer_id, got codes {codes}"
    recommended = set(payload.get("recommended_exclude_columns", []))
    assert "customer_id" in recommended, f"Expected customer_id in recommended excludes, got {recommended}"
    assert "application_date" in recommended, f"Expected application_date in recommended excludes, got {recommended}"
    assert "default_date" in recommended, f"Expected default_date in recommended excludes, got {recommended}"
    assert "months_since_default" in recommended, f"Expected months_since_default in recommended excludes, got {recommended}"


def test_profile_quality_flags_statistical_issues() -> None:
    """Constant, dominant, high-cardinality, null-heavy, and string-numeric columns."""
    df = pl.DataFrame({
        "constant_col": [1] * 20,
        "dominant_col": ["X"] * 19 + ["Y"],
        "merchant_id": [f"M_{i}" for i in range(20)],
        "mostly_null": pl.Series([None] * 12 + [1.0] * 8, dtype=pl.Float64),
        "income_str": [str(i * 1000) for i in range(20)],
        "target": ["good"] * 15 + ["bad"] * 5,
    })
    payload, _ = _profile_of(df)
    codes = {w["code"] for w in payload.get("quality_warnings", [])}
    assert "CONSTANT_COLUMN" in codes, f"Expected CONSTANT_COLUMN, got {codes}"
    assert "DOMINANT_VALUE_COLUMN" in codes, f"Expected DOMINANT_VALUE_COLUMN, got {codes}"
    assert "HIGH_CARDINALITY_CATEGORICAL" in codes, f"Expected HIGH_CARDINALITY_CATEGORICAL, got {codes}"
    assert "NULL_HEAVY_COLUMN" in codes, f"Expected NULL_HEAVY_COLUMN, got {codes}"
    assert "STRING_CODED_NUMERIC" in codes, f"Expected STRING_CODED_NUMERIC, got {codes}"


def test_profile_quality_flags_duplicate_rows_and_bad_headers() -> None:
    """Duplicate rows and blank/duplicate column names should be flagged."""
    df = pl.DataFrame({
        "": [1, 1, 2, 3],                     # blank column name
        "a_duplicated_0": [4, 4, 5, 6],       # duplicate imported name
        "value": [1, 1, 2, 3],                # rows 0 and 1 are duplicates
    })
    payload, _ = _profile_of(df)
    codes = {w["code"] for w in payload.get("quality_warnings", [])}
    assert "DUPLICATE_ROWS" in codes, f"Expected DUPLICATE_ROWS, got {codes}"
    assert "BLANK_COLUMN_NAME" in codes, f"Expected BLANK_COLUMN_NAME, got {codes}"
    assert "DUPLICATE_IMPORTED_COLUMN_NAME" in codes, f"Expected DUPLICATE_IMPORTED_COLUMN_NAME, got {codes}"


def test_profile_quality_flags_date_like_strings() -> None:
    """Utf8 column with date-like strings should be flagged."""
    df = pl.DataFrame({
        "description": ["a", "b", "c", "d", "e"],
        "event_date": [
            "2024-01-01", "2024-02-15", "2024-03-20",
            "2024-04-10", "2024-05-05",
        ],
        "target": [1, 0, 1, 0, 1],
    })
    payload, _ = _profile_of(df)
    codes = {w["code"] for w in payload.get("quality_warnings", [])}
    assert "DATE_LIKE_STRING" in codes, f"Expected DATE_LIKE_STRING, got {codes}"


# Run with: python3 -m pytest tests/test_dataset_quality.py -x -q
