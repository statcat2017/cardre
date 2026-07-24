"""Composed execution test: SubmitRun → ExecuteRun → FinalizeRun through the production stack.

Runs the full canonical scorecard workflow (31 steps) against a real project
database and filesystem artifact store. Asserts run succeeded, all steps
succeeded, evidence edges exist, manifest was published, artifacts are stored.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
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


@pytest.fixture
def composed_run(tmp_path):
    """Provision a project, create a plan with canonical scorecard steps,
    submit and execute the run synchronously, and return metadata.

    Yields (project_id, plan_id, pv_id, run_id, uow_factory, root).
    """
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test Project")
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        uow.commit()
    registry.register(project_id, root)

    csv_path = _write_input_csv(tmp_path / "input.csv")
    steps = build_canonical_scorecard_steps(csv_path)

    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(launch_mode=True, registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )

    return project_id, plan_id, pv_id, result.run_id, uow_factory, root


class TestComposedExecution:
    def test_run_succeeds(self, composed_run):
        _, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(composed_run[0]) as uow:
            run = uow.runs.get(run_id)
        assert run is not None
        assert run.status == "succeeded", f"Run status: {run.status}"

    def test_all_steps_succeed(self, composed_run):
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            steps = uow.run_steps.get_for_run(run_id)
        assert len(steps) > 5, f"Too few steps: {len(steps)}"
        for s in steps:
            assert s.status.value == "succeeded", f"Step {s.step_id}: {s.status}"

    def test_evidence_edges_created(self, composed_run):
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            count = uow._conn.execute(
                "SELECT COUNT(*) FROM evidence_edges WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
        assert count > 0, "No evidence edges created"

    def test_manifest_published(self, composed_run):
        """Verify the canonical run manifest was published by FinalizeRun."""
        _, _, _, run_id, _, root = composed_run
        manifest_path = root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists(), f"Manifest not found: {manifest_path}"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "succeeded"
        assert manifest["manifest_hash"]

    def test_artifacts_stored(self, composed_run):
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            lineage = uow._conn.execute(
                "SELECT DISTINCT artifact_id FROM artifact_lineage WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        assert len(lineage) > 0, "No artifact lineage"
        first = lineage[0]["artifact_id"]
        with uow_factory.for_project(project_id) as uow:
            art = uow.artifacts.get(first)
        assert art is not None
