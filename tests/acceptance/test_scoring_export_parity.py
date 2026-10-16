"""Full end-to-end scoring-export parity test.

Runs the complete canonical scorecard workflow through the API, then compares
scores from the generated Python scorer and SQL scorer against the apply-model
reference output for every row in train/test/oot. This is the only test here
that exercises the full product pathway; the compiler/IR, generated-Python, and
SQL unit tests live in ``tests/nodes/``.
"""
from __future__ import annotations

import sqlite3
from io import BytesIO
from typing import Any

import polars as pl

from cardre.bootstrap.node_catalogue import build_default_catalogue
from tests.acceptance.fixture_pathway import build_acceptance_fixture_steps, write_input_parquet


def test_scoring_export_parity(api_client, tmp_path):
    project_dir = tmp_path / "parity.cardre"
    resp = api_client.post("/projects", json={"name": "Parity", "path": str(project_dir)})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]

    parquet_path = write_input_parquet(tmp_path / "input.parquet")

    resp = api_client.post(
        f"/projects/{project_id}/plans",
        json={"name": "Parity Plan"},
    )
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["plan_id"]

    container = api_client.app.state.container
    cat = build_default_catalogue()
    steps = build_acceptance_fixture_steps(parquet_path, cat)

    with container.uow_factory.for_project(project_id) as uow:
        plan_version_id = uow.plans.create_version(
            plan_id, steps=steps, is_committed=True,
        )
        uow.commit()

    resp = api_client.post(
        f"/projects/{project_id}/runs",
        json={"plan_version_id": plan_version_id, "sync": True, "force": True},
    )
    assert resp.status_code == 201, resp.text
    run_data = resp.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "succeeded", f"Run did not succeed: {run_data}"

    root = container.project_registry.resolve_root(project_id)
    artifacts: list[dict[str, Any]] = []
    with container.uow_factory.read_only(project_id) as uow:
        run_steps = uow.run_steps.get_for_run(run_id)
        for step in run_steps:
            for art in uow.artifacts.output_artifacts_for_run_step(step.run_step_id):
                artifacts.append({
                    "artifact_id": art.artifact_id,
                    "artifact_type": art.artifact_type,
                    "role": art.role,
                    "path": art.path,
                    "step_id": step.step_id,
                })

        apply_model_parquet = [
            row for row in artifacts
            if row["step_id"] == "apply-model" and row["role"] in {"train", "test", "oot"}
        ]
        assert len(apply_model_parquet) >= 2, (
            "apply-model should produce at least two of train/test/oot parquet "
            "(partial apply is intentional)"
        )

        python_export = [
            row for row in artifacts
            if row["step_id"] == "scoring-export-python"
            and row["artifact_type"] == "scoring_export_python"
        ]
        assert python_export, "scoring-export-python artifact not found"
        sql_export = [
            row for row in artifacts
            if row["step_id"] == "scoring-export-sql"
            and row["artifact_type"] == "scoring_export_sql"
        ]
        assert sql_export, "scoring-export-sql artifact not found"
        scorecard_export = [
            row for row in artifacts
            if row["step_id"] == "scorecard-table-export"
            and row["artifact_type"] == "scorecard_table"
        ]
        assert scorecard_export, "scorecard table artifact not found"

        listed_response = api_client.get(
            f"/projects/{project_id}/exports", params={"run_id": run_id},
        )
        assert listed_response.status_code == 200, listed_response.text
        exports = listed_response.json()["exports"]
        exports_by_type = {item["export_type"]: item for item in exports}
        assert set(exports_by_type) == {"scorecard_csv", "python_scorer", "sql_scorer"}

        expected_files = {
            "scorecard_csv": ("scorecard.csv", "text/csv"),
            "python_scorer": ("scorecard.py", "text/x-python"),
            "sql_scorer": ("scorecard.sql", "application/sql"),
        }
        for export_type, (file_name, media_type) in expected_files.items():
            assert exports_by_type[export_type]["file_name"] == file_name
            assert exports_by_type[export_type]["media_type"] == media_type
            assert exports_by_type[export_type]["artifact_id"]

        csv_item = exports_by_type["scorecard_csv"]
        csv_response = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/exports/download",
            params={"artifact_id": csv_item["artifact_id"]},
        )
        assert csv_response.status_code == 200, csv_response.text
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert 'filename="scorecard.csv"' in csv_response.headers["content-disposition"]
        downloaded_table = pl.read_csv(BytesIO(csv_response.content))
        persisted_table = pl.read_parquet(root / scorecard_export[0]["path"])
        assert downloaded_table.columns == ["variable", "bin_id", "label", "woe", "coefficient", "points"]
        assert downloaded_table.height == persisted_table.height
        for column in ("variable", "bin_id", "label"):
            assert downloaded_table[column].to_list() == persisted_table[column].to_list()
        for column in ("woe", "coefficient", "points"):
            for actual, expected in zip(
                downloaded_table[column].to_list(), persisted_table[column].to_list(), strict=True,
            ):
                assert abs(actual - expected) <= 1e-8

        python_item = exports_by_type["python_scorer"]
        python_response = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/exports/download",
            params={"artifact_id": python_item["artifact_id"]},
        )
        assert python_response.status_code == 200, python_response.text
        assert python_response.headers["content-type"].startswith("text/x-python")
        assert 'filename="scorecard.py"' in python_response.headers["content-disposition"]
        python_source = python_response.text
        assert python_source.startswith('"""Standalone scorecard scorer')

        sql_item = exports_by_type["sql_scorer"]
        sql_response = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/exports/download",
            params={"artifact_id": sql_item["artifact_id"]},
        )
        assert sql_response.status_code == 200, sql_response.text
        assert sql_response.headers["content-type"].startswith("application/sql")
        assert 'filename="scorecard.sql"' in sql_response.headers["content-disposition"]
        sql_source = sql_response.text
        assert sql_source.startswith("-- Standalone scorecard SQL")

        other_project = api_client.post(
            "/projects", json={"name": "Other project", "path": str(root.parent / "other.cardre")},
        )
        assert other_project.status_code == 201, other_project.text
        foreign_download = api_client.get(
            f"/projects/{other_project.json()['project_id']}/runs/{run_id}/exports/download",
            params={"artifact_id": python_item["artifact_id"]},
        )
        assert foreign_download.status_code == 404
        assert foreign_download.json()["detail"]["code"] == "RUN_NOT_FOUND"

        unknown_download = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/exports/download",
            params={"artifact_id": "not-an-output-artifact"},
        )
        assert unknown_download.status_code == 404
        assert unknown_download.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"

        for row in apply_model_parquet:
            role = row["role"]
            df = pl.read_parquet(root / row["path"])
            assert "score" in df.columns, f"apply-model {role} missing score column"
            assert "cardre_scaled_score" not in df.columns, (
                f"apply-model {role} still writes removed cardre_scaled_score column"
            )

            ref_scores = df["score"].to_list()
            records = df.drop(["score", "predicted_bad_probability",
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
