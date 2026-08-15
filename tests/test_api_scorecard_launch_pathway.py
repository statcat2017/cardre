"""Full scorecard launch pathway acceptance test, driven through the project-scoped API.

This is the v2 Phase 5 DoD acceptance test: create project via POST /projects,
create plan via API, seed a committed plan version with all scorecard nodes
via PlanRepository, run synchronously through POST /projects/{project_id}/runs,
then verify steps, evidence, and store-level integrity.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import polars as pl
import pytest

from cardre._evidence.schemas import (
    SCHEMA_CALIBRATION_DIAGNOSTICS,
    SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS,
    SCHEMA_SCORE_TABLE,
    SCHEMA_SCORING_EXPORT_PYTHON,
    SCHEMA_SCORING_EXPORT_SQL,
    SCHEMA_SEPARATION_DIAGNOSTICS,
    SCHEMA_VIF_DIAGNOSTICS,
)
from cardre.workflows import build_canonical_scorecard_steps, canonical_scorecard_step_ids

pytestmark = pytest.mark.governance


def _write_input_csv(path: Path) -> Path:
    """Generate a small synthetic binary-classification dataset."""
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


EXPECTED_STEP_IDS = canonical_scorecard_step_ids()
EXPECTED_STEP_COUNT = len(EXPECTED_STEP_IDS)


def test_full_scorecard_launch_pathway_via_api(monkeypatch, tmp_path):
    """Full canonical scorecard pathway through the project-scoped API.

    Phases:
      1. POST /projects (fresh store bootstrap)
      2. POST .../plans
      3. Seed committed plan version via PlanRepository (no add-step API route)
      4. POST .../runs with sync=True, force=True
      5. GET .../runs/{id}/steps — all canonical workflow steps succeeded
      6. GET .../runs/{id}/evidence — every non-root step has evidence
      7. Store-level integrity: every non-root run_step has evidence_edges,
          and every evidence_edge has at least one evidence_artifact.
    """
    from fastapi.testclient import TestClient

    from cardre.api.app import create_app
    from cardre.bootstrap.container import build_container
    from cardre.bootstrap.settings import Settings

    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))
    settings = Settings.from_env()
    container = build_container(settings)
    api_client = TestClient(create_app(container))

    # 1. Create project via POST /projects
    project_dir = tmp_path / "scorecard.cardre"
    resp = api_client.post("/projects", json={"name": "Scorecard", "path": str(project_dir)})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]
    headers = {"X-Project-Path": str(project_dir)}

    # 2. Create input CSV
    csv_path = _write_input_csv(tmp_path / "input.csv")

    # 3. Create plan via API
    resp = api_client.post(
        f"/projects/{project_id}/plans",
        headers=headers,
        json={"name": "Scorecard Plan"},
    )
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["plan_id"]

    # 4. Seed a committed plan version with the scorecard graph.
    #    There is no "add step" API route, so we open the store directly
    #    and use the UoW — acceptable for test setup.
    steps = build_canonical_scorecard_steps(csv_path)
    with container.uow_factory.for_project(project_id) as uow:
        plan_version_id = uow.plans.create_version(
            plan_id, steps=steps, is_committed=True,
        )

    # 5. POST /projects/{project_id}/runs — create and execute synchronously
    resp = api_client.post(
        f"/projects/{project_id}/runs",
        headers=headers,
        json={"plan_version_id": plan_version_id, "sync": True, "force": True},
    )
    assert resp.status_code == 201, resp.text
    run_data = resp.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "succeeded", f"Run did not succeed: {run_data}"

    # 6. GET /projects/{project_id}/runs/{run_id}/steps — verify all succeeded
    resp = api_client.get(
        f"/projects/{project_id}/runs/{run_id}/steps",
        headers=headers,
    )
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == EXPECTED_STEP_COUNT
    actual_step_ids = [s["step_id"] for s in steps]
    assert set(actual_step_ids) == set(EXPECTED_STEP_IDS)
    for earlier, later in [
        ("manual-binning", "final-woe-iv"),
        ("final-woe-iv", "woe-transform-train"),
        ("woe-transform-train", "model-fit"),
        ("model-fit", "coefficient-sign-check"),
        ("model-fit", "separation-diagnostics"),
        ("woe-transform-train", "vif-diagnostics"),
        ("coefficient-sign-check", "score-scaling"),
        ("model-fit", "score-scaling"),
        ("freeze-scorecard-bundle", "apply-woe"),
        ("apply-woe", "apply-model"),
        ("apply-model", "calibration-diagnostics"),
        ("calibration-diagnostics", "validation-metrics"),
        ("apply-model", "validation-metrics"),
        ("apply-model", "cutoff-analysis"),
        ("cutoff-analysis", "scorecard-table-export"),
        ("scorecard-table-export", "scoring-export-python"),
        ("scoring-export-python", "scoring-export-sql"),
    ]:
        assert actual_step_ids.index(earlier) < actual_step_ids.index(later)
    for s in steps:
        assert s["status"] == "succeeded", f"Step {s['step_id']} failed: {s}"

    # 7. GET /projects/{project_id}/runs/{run_id}/evidence — verify edges
    resp = api_client.get(
        f"/projects/{project_id}/runs/{run_id}/evidence",
        headers=headers,
    )
    assert resp.status_code == 200
    evidence = resp.json()
    # import-data is root (no parents) => no edge; all others have >= 1 edge
    non_root = EXPECTED_STEP_COUNT - 1
    assert len(evidence) >= non_root, (
        f"Expected >= {non_root} evidence edges, got {len(evidence)}"
    )

    # 8. Open store directly for integrity assertions (Phase 5 abort criterion).
    with container.uow_factory.read_only(project_id) as uow:
        run_steps = uow.run_steps.get_for_run(run_id)
        artifact_rows = []
        for rs in run_steps:
            for direction, art in uow.artifacts.artifacts_for_run_step(rs.run_step_id):
                if direction == "output":
                    artifact_rows.append({
                        "artifact_id": art.artifact_id,
                        "role": art.role,
                        "path": art.path,
                        "media_type": art.media_type,
                        "metadata_json": json.dumps(art.metadata),
                        "step_id": rs.step_id,
                    })

        # Every non-root run step has at least one evidence_edges row.
        # technical-manifest is the exception: its input is a runtime-injected
        # synthetic RunSummary (own-step bucket), not a parent step's output.
        for rs in run_steps:
            if rs.step_id in ("import", "technical-manifest"):
                continue
            edges = uow.evidence.get_edges_for_run_step(rs.run_step_id)
            assert len(edges) >= 1, f"Step {rs.step_id} has no evidence edges"

        # Every evidence_edge has at least one evidence_artifact
        for rs in run_steps:
            for edge in uow.evidence.get_edges_for_run_step(rs.run_step_id):
                arts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                assert arts, f"Edge {edge.evidence_edge_id} has no artifacts"

        final_woe_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "final-woe-iv"
            and '"schema_version": "cardre.woe_iv_evidence.v1"' in row["metadata_json"]
        ]
        assert final_woe_artifacts, "final-woe-iv did not produce cardre.woe_iv_evidence.v1"

        coefficient_sign_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "coefficient-sign-check"
            and f'"schema_version": "{SCHEMA_COEFFICIENT_SIGN_DIAGNOSTICS}"' in row["metadata_json"]
        ]
        assert coefficient_sign_artifacts, "coefficient-sign-check did not produce structured diagnostics"
        coefficient_sign_payload = json.loads(
            (project_dir / coefficient_sign_artifacts[0]["path"]).read_text(encoding="utf-8")
        )
        assert {"conventions", "summary", "variables"} <= set(coefficient_sign_payload)

        separation_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "separation-diagnostics"
            and f'"schema_version": "{SCHEMA_SEPARATION_DIAGNOSTICS}"' in row["metadata_json"]
        ]
        assert separation_artifacts, "separation-diagnostics did not produce structured diagnostics"
        separation_payload = json.loads(
            (project_dir / separation_artifacts[0]["path"]).read_text(encoding="utf-8")
        )
        assert {"summary", "variables", "threshold"} <= set(separation_payload)

        vif_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "vif-diagnostics"
            and f'"schema_version": "{SCHEMA_VIF_DIAGNOSTICS}"' in row["metadata_json"]
        ]
        assert vif_artifacts, "vif-diagnostics did not produce structured diagnostics"
        vif_payload = json.loads(
            (project_dir / vif_artifacts[0]["path"]).read_text(encoding="utf-8")
        )
        assert {"summary", "variables", "threshold"} <= set(vif_payload)

        calibration_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "calibration-diagnostics"
            and f'"schema_version": "{SCHEMA_CALIBRATION_DIAGNOSTICS}"' in row["metadata_json"]
        ]
        assert calibration_artifacts, "calibration-diagnostics did not produce structured diagnostics"
        calibration_payload = json.loads(
            (project_dir / calibration_artifacts[0]["path"]).read_text(encoding="utf-8")
        )
        assert {"conventions", "roles", "summary"} <= set(calibration_payload)

        exclusion_summary = [
            row for row in artifact_rows
            if row["step_id"] == "apply-exclusions"
            and '"schema_version": "cardre.exclusion_summary.v1"' in row["metadata_json"]
        ]
        assert exclusion_summary, "apply-exclusions did not produce exclusion summary evidence"

        sample_definition = [
            row for row in artifact_rows
            if row["step_id"] == "sample-definition"
            and '"schema_version": "cardre.sample_definition.v1"' in row["metadata_json"]
        ]
        assert sample_definition, "sample-definition did not produce sample definition evidence"

        treatment_reports = [
            row for row in artifact_rows
            if row["step_id"] == "explicit-missing-outlier-treatment"
            and row["role"] == "report"
        ]
        assert treatment_reports, "explicit-missing-outlier-treatment did not produce a treatment report"

        modelling_metadata = next(
            row for row in artifact_rows
            if row["step_id"] == "define-metadata" and row["role"] == "definition"
        )
        modelling_metadata_payload = json.loads((project_dir / modelling_metadata["path"]).read_text())
        assert modelling_metadata_payload["purpose"] == "application_credit_scorecard"
        assert modelling_metadata_payload["product"] == "term_loan"
        assert modelling_metadata_payload["segment"] == "retail"
        assert modelling_metadata_payload["observation_window"] == "2024-01_to_2024-06"
        assert modelling_metadata_payload["performance_window"] == "2024-07_to_2024-12"
        assert modelling_metadata_payload["reject_inference_position"] == "not_applied"

        scored_outputs = [
            row for row in artifact_rows
            if row["step_id"] == "apply-model" and row["role"] in {"train", "test"}
        ]
        assert {row["role"] for row in scored_outputs} == {"train", "test"}
        for row in scored_outputs:
            df = pl.read_parquet(project_dir / row["path"])
            assert "predicted_bad_probability" in df.columns
            assert "score" in df.columns

        validation_metrics_reports = [
            row for row in artifact_rows
            if row["step_id"] == "validation-metrics" and row["role"] == "report"
        ]
        assert validation_metrics_reports, "validation-metrics did not produce a report"
        validation_payload = json.loads((project_dir / validation_metrics_reports[0]["path"]).read_text())
        assert "train" in validation_payload["roles"]
        assert "test" in validation_payload["roles"]

        scorecard_table_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "scorecard-table-export"
            and f'"schema_version": "{SCHEMA_SCORE_TABLE}"' in row["metadata_json"]
            and row["media_type"] == "application/json"
        ]
        assert scorecard_table_artifacts, "scorecard-table-export did not produce scorecard_table.v1 JSON"
        scorecard_table_payload = json.loads(
            (project_dir / scorecard_table_artifacts[0]["path"]).read_text(encoding="utf-8")
        )
        assert "rows" in scorecard_table_payload
        assert len(scorecard_table_payload["rows"]) > 0
        for row in scorecard_table_payload["rows"]:
            assert {"variable", "bin_id", "label", "woe", "coefficient", "points"} <= set(row)

        # Verify tabular artifact also exists (parquet table, the CSV equivalent)
        csv_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "scorecard-table-export"
            and row["media_type"] == "application/vnd.apache.parquet"
        ]
        assert csv_artifacts, "scorecard-table-export did not produce tabular artifact"

        python_export_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "scoring-export-python"
            and f'"schema_version": "{SCHEMA_SCORING_EXPORT_PYTHON}"' in row["metadata_json"]
        ]
        assert python_export_artifacts, "scoring-export-python did not produce scoring_export_python.v1"
        python_export_payload = json.loads(
            (project_dir / python_export_artifacts[0]["path"]).read_text(encoding="utf-8")
        )
        assert "source" in python_export_payload
        assert "def score_cardre" in python_export_payload["source"]

        sql_export_artifacts = [
            row for row in artifact_rows
            if row["step_id"] == "scoring-export-sql"
            and f'"schema_version": "{SCHEMA_SCORING_EXPORT_SQL}"' in row["metadata_json"]
        ]
        assert sql_export_artifacts, "scoring-export-sql did not produce scoring_export_sql.v1"
        sql_export_payload = json.loads(
            (project_dir / sql_export_artifacts[0]["path"]).read_text(encoding="utf-8")
        )
        assert "source" in sql_export_payload
        assert "CASE" in sql_export_payload["source"]
