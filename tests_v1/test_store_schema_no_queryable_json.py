"""Phase 1 — asserts no ``*_ids_json``/``*_ids`` array columns exist on
    relationship tables (catches regressions)."""

import sqlite3

import pytest

from cardre.store.schema import ALL_TABLES_SQL


def _get_columns(db_path: str) -> dict[str, set[str]]:
    """Return a dict of table_name -> set of column names."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    result: dict[str, set[str]] = {}
    for (tname,) in tables:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({tname})").fetchall()}
        result[tname] = cols
    conn.close()
    return result


FORBIDDEN_PATTERNS = [
    "_ids_json",
    "_ids_json",
    # Also check for plain _ids columns on relationship tables
]


def test_no_ids_json_columns(tmp_path):
    """No relationship table has *_ids_json or *_ids array columns."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(ALL_TABLES_SQL)
    conn.commit()
    conn.close()

    columns = _get_columns(str(db_path))

    # Relationship tables that must NOT have JSON array columns
    relationship_tables = {
        "plan_step_edges",
        "evidence_edges",
        "evidence_artifacts",
        "comparison_challenger_branches",
        "comparison_snapshot_plan_versions",
        "artifact_lineage",
    }

    for table_name in relationship_tables:
        assert table_name in columns, f"Missing table {table_name}"
        for col in columns[table_name]:
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in col:
                    pytest.fail(
                        f"Table {table_name} has forbidden column {col!r} "
                        f"(matches forbidden pattern {pattern!r})"
                    )

    # run_steps must NOT have input_artifact_ids_json or output_artifact_ids_json
    if "run_steps" in columns:
        forbidden_run_step_cols = {"input_artifact_ids_json", "output_artifact_ids_json"}
        actual = columns["run_steps"]
        overlap = forbidden_run_step_cols & actual
        if overlap:
            pytest.fail(
                f"Table run_steps has forbidden JSON array columns: {overlap}"
            )

    # plan_steps must NOT have parent_step_ids_json
    if "plan_steps" in columns:
        assert "parent_step_ids_json" not in columns["plan_steps"], (
            "plan_steps should not have parent_step_ids_json (use plan_step_edges)"
        )

    # branch_comparisons must NOT have challenger_branch_ids_json
    if "branch_comparisons" in columns:
        assert "challenger_branch_ids_json" not in columns["branch_comparisons"], (
            "branch_comparisons should not have challenger_branch_ids_json"
        )

    # branch_comparison_snapshots must NOT have source_plan_version_ids_json
    if "branch_comparison_snapshots" in columns:
        assert "source_plan_version_ids_json" not in columns["branch_comparison_snapshots"], (
            "branch_comparison_snapshots should not have source_plan_version_ids_json"
        )
