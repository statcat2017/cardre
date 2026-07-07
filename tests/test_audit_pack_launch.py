"""Audit-pack launch acceptance test.

Runs the full canonical scorecard workflow, then exports an audit pack
and verifies its contents.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

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


def test_audit_pack_launch(raw_project_path, api_client, tmp_path):
    project_dir = tmp_path / "audit.cardre"
    resp = api_client.post("/projects", json={"name": "Audit", "path": str(project_dir)})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]
    headers = {"X-Project-Path": str(project_dir)}

    csv_path = _write_input_csv(tmp_path / "input.csv")

    resp = api_client.post(
        f"/projects/{project_id}/plans",
        headers=headers,
        json={"name": "Audit Plan"},
    )
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["plan_id"]

    from cardre.store.branch_repo import BranchRepository
    from cardre.store.db import ProjectStore
    from cardre.store.plan_repo import PlanRepository

    store = ProjectStore(project_dir)
    store.open()
    try:
        steps = build_canonical_scorecard_steps(csv_path)
        plan_version_id = PlanRepository(store).create_version(
            plan_id, steps=steps, is_committed=True,
        )

        branch_repo = BranchRepository(store)
        branch_id = branch_repo.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="main",
            branch_type="feature",
            base_plan_version_id=plan_version_id,
            head_plan_version_id=plan_version_id,
            created_reason="audit test",
        )

        for s in steps:
            branch_repo.create_step_map(
                branch_id=branch_id,
                plan_version_id=plan_version_id,
                canonical_step_id=s.canonical_step_id,
                step_id=s.step_id,
                is_branch_owned=True,
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
    assert run_data["status"] == "succeeded", f"Run did not succeed: {run_data}"

    store = ProjectStore(project_dir)
    store.open()
    try:
        from cardre.services.export_service import export_branch_audit_pack

        result = export_branch_audit_pack(
            store=store,
            project_id=project_id,
            plan_id=plan_id,
            branch_id=branch_id,
            include_report=True,
        )

        assert result["file_count"] > 0, "Export produced no files"
        assert not result["partial"], "Export should not be partial"

        export_path = Path(result["export_path"])
        assert export_path.exists(), f"Export path {export_path} does not exist"

        expected_files = [
            "project.json",
            "branch.json",
            "branch_step_map.json",
            "plan_steps.json",
            "runs.json",
            "run_steps.json",
            "artifacts.json",
            "checksums.sha256",
        ]
        for fname in expected_files:
            assert (export_path / fname).exists(), f"Missing expected file: {fname}"

        # Verify no row-level dataset artifacts in artifacts/ subdirectory
        # (WOE tables are parquet but are evidence, not row-level data)
        artifacts_data = json.loads((export_path / "artifacts.json").read_text())
        for a in artifacts_data:
            if a.get("artifact_type") in ("dataset", "tabular"):
                raise AssertionError(f"Row-level artifact found in export: {a['artifact_id']} ({a['artifact_type']})")

        # Verify checksums.sha256 is valid
        checksum_path = export_path / "checksums.sha256"
        checksum_lines = checksum_path.read_text().strip().split("\n")
        assert len(checksum_lines) > 0, "checksums.sha256 is empty"
        for line in checksum_lines:
            parts = line.split("  ", 1)
            assert len(parts) == 2, f"Invalid checksum line: {line}"
            hex_digest, rel_path = parts
            assert len(hex_digest) == 64, f"Invalid hex digest length: {hex_digest}"
            int(hex_digest, 16)  # raises if not hex
            assert (export_path / rel_path).exists(), (
                f"Checksum references non-existent file: {rel_path}"
            )

        # Verify project.json has expected content
        project_data = json.loads((export_path / "project.json").read_text())
        assert project_data.get("project_id") == project_id

        # Verify branch.json has expected content
        branch_data = json.loads((export_path / "branch.json").read_text())
        assert branch_data.get("branch_id") == branch_id

        # Verify artifacts.json has non-row-level evidence artifacts
        artifacts_data = json.loads((export_path / "artifacts.json").read_text())
        assert len(artifacts_data) > 0, "artifacts.json should contain evidence artifacts"
        artifact_types = {a["artifact_type"] for a in artifacts_data}
        # Should include non-row-level evidence like reports, manifests, scorecards
        assert "report" in artifact_types or "scorecard" in artifact_types or "manifest" in artifact_types, (
            f"Expected evidence artifacts, got types: {artifact_types}"
        )

        # Verify runs.json has the run
        runs_data = json.loads((export_path / "runs.json").read_text())
        assert len(runs_data) == 1, f"Expected 1 run, got {len(runs_data)}"
        assert runs_data[0]["status"] == "succeeded"

        # Verify run_steps.json has canonical steps
        run_steps_data = json.loads((export_path / "run_steps.json").read_text())
        assert len(run_steps_data) > 0, "run_steps.json should contain run steps"
        step_ids = {rs["step_id"] for rs in run_steps_data}
        for key_step in ("apply-model", "validation-metrics", "cutoff-analysis", "scorecard-table-export"):
            assert key_step in step_ids, f"Missing key step {key_step} in run_steps.json"

        # Verify report was generated
        report_dir = export_path / "report"
        assert report_dir.exists(), "Report directory should exist when include_report=True"
        assert (report_dir / "report_bundle.json").exists(), "Missing report_bundle.json"
        assert (report_dir / "report.html").exists(), "Missing report.html"
    finally:
        store.close()
