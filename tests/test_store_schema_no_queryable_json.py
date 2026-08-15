from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def conn(tmp_path):
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner

    root = tmp_path / "project"
    SqliteProjectProvisioner().initialize(root)
    c = sqlite3.connect(root / "project.sqlite")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_relationship_tables_do_not_store_id_arrays(conn) -> None:
    tables = (
        "plan_steps",
        "plan_step_edges",
        "runs",
        "run_steps",
        "artifacts",
        "artifact_lineage",
        "evidence_edges",
        "evidence_artifacts",
        "branch_step_map",
    )

    for table in tables:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert not any(column.endswith("_ids_json") for column in columns)
        assert not any(column.endswith("_ids") for column in columns)
