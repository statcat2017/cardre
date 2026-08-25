from __future__ import annotations


def test_relationship_tables_do_not_store_id_arrays(provisioned_project) -> None:
    project_id, uow_factory, _, _ = provisioned_project
    tables = (
        "plan_steps",
        "plan_step_edges",
        "runs",
        "run_steps",
        "artifacts",
        "artifact_lineage",
        "evidence_edges",
        "evidence_artifacts",
    )

    with uow_factory.for_project(project_id) as uow:
        for table in tables:
            columns = {
                row["name"]
                for row in uow._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert not any(column.endswith("_ids_json") for column in columns)
            assert not any(column.endswith("_ids") for column in columns)
