"""Full end-to-end scoring-export parity test.

Runs the complete canonical scorecard workflow through the API, then compares
scores from the generated Python scorer and SQL scorer against the apply-model
reference output for every row in train/test/oot. This is the only test here
that exercises the full product pathway; the compiler/IR, generated-Python, and
SQL unit tests live in ``tests/nodes/``.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import polars as pl

from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.domain.evidence.schemas import SCHEMA_SCORING_EXPORT_PYTHON, SCHEMA_SCORING_EXPORT_SQL
from tests.acceptance.fixture_pathway import build_acceptance_fixture_steps


def _write_input_parquet(path: Path) -> Path:
    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    pl.DataFrame(rows).write_parquet(path)
    return path


def test_scoring_export_parity(api_client, tmp_path):
    project_dir = tmp_path / "parity.cardre"
    resp = api_client.post("/projects", json={"name": "Parity", "path": str(project_dir)})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]

    parquet_path = _write_input_parquet(tmp_path / "input.parquet")

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
                    "role": art.role,
                    "path": art.path,
                    "metadata_json": json.dumps(art.metadata or {}),
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
            and f'"schema_version": "{SCHEMA_SCORING_EXPORT_PYTHON}"' in row["metadata_json"]
        ]
        assert python_export, "scoring-export-python artifact not found"
        python_payload = json.loads(
            (root / python_export[0]["path"]).read_text(encoding="utf-8")
        )
        python_source = python_payload["source"]

        sql_export = [
            row for row in artifacts
            if row["step_id"] == "scoring-export-sql"
            and f'"schema_version": "{SCHEMA_SCORING_EXPORT_SQL}"' in row["metadata_json"]
        ]
        assert sql_export, "scoring-export-sql artifact not found"
        sql_payload = json.loads(
            (root / sql_export[0]["path"]).read_text(encoding="utf-8")
        )
        sql_source = sql_payload["source"]

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
