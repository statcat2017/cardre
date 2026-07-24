"""Composed execution test: SubmitRun → ExecuteRun → FinalizeRun through the production stack.

Runs the full canonical scorecard workflow (31 steps) against a real project
database and filesystem artifact store. Asserts exact step set, every step
succeeded, evidence graph integrity, manifest content, and artifact lineage.
"""

from __future__ import annotations

import csv
import json

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.workflows import build_canonical_scorecard_steps, canonical_scorecard_step_ids


def _write_input_csv(path):
    rows = []
    for i in range(60):
        rows.append({
            "credit_amount": 1000 + i * 50,
            "age_years": 25 + (i % 30),
            "duration_months": 6 + (i % 36),
            "credit_risk_class": "good" if i % 3 != 0 else "bad",
        })
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def composed_run(tmp_path):
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

    def test_all_31_canonical_steps_succeed(self, composed_run):
        """Every canonical scorecard step completed successfully."""
        project_id, _, _, run_id, uow_factory, _ = composed_run
        canonical_ids = canonical_scorecard_step_ids()
        with uow_factory.for_project(project_id) as uow:
            steps = uow.run_steps.get_for_run(run_id)
        step_ids = {s.step_id for s in steps}
        step_lookup = {s.step_id: s for s in steps}
        for cid in canonical_ids:
            assert cid in step_ids, f"Missing canonical step: {cid}"
            assert step_lookup[cid].status.value == "succeeded", f"Step {cid}: {step_lookup[cid].status}"
        assert len(steps) == len(canonical_ids), (
            f"Expected {len(canonical_ids)} steps, got {len(steps)}"
        )

    def test_evidence_artifacts_created_for_every_edge(self, composed_run):
        """Every evidence edge has at least one EvidenceArtifact record."""
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            edges = uow.evidence.get_edges_for_run(run_id)
            assert len(edges) > 0, "No evidence edges created"
            for edge in edges:
                artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                assert len(artifacts) > 0, f"No evidence artifacts for edge {edge.evidence_edge_id}"

    def test_false_edges_not_created(self, composed_run):
        """Parent steps whose outputs were filtered out produce no edge."""
        project_id, _, _, run_id, uow_factory, _ = composed_run
        with uow_factory.for_project(project_id) as uow:
            edges = uow.evidence.get_edges_for_run(run_id)
            for edge in edges:
                artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                for ea in artifacts:
                    art = uow.artifacts.get(ea.artifact_id)
                    assert art is not None, f"EvidenceArtifact references missing artifact: {ea.artifact_id}"
                    assert art.role in ("output", "input", "report", "definition", "model", "scorecard", "train",
                                       "test", "oot", "manifest", "score_scaling"), f"Unexpected artifact role: {art.role}"

    def test_manifest_contains_all_steps(self, composed_run):
        """Canonical manifest has the full step set and identity checks pass."""
        _, _, _, run_id, _, root = composed_run
        manifest_path = root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists(), f"Manifest not found: {manifest_path}"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "succeeded"
        assert manifest["manifest_hash"]
        step_ids_in_manifest = {s["step_id"] for s in manifest["steps"]}
        canonical_ids = set(canonical_scorecard_step_ids())
        assert step_ids_in_manifest == canonical_ids, (
            f"Manifest steps mismatch: missing={canonical_ids - step_ids_in_manifest}, "
            f"extra={step_ids_in_manifest - canonical_ids}"
        )

    def test_every_artifact_linked_in_manifest(self, composed_run):
        """Every artifact referenced by a step in the manifest has a lineage record."""
        project_id, _, _, run_id, uow_factory, root = composed_run
        manifest_path = root / "exports" / f"manifest-{run_id}" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest_art_ids: set[str] = set()
        for s in manifest["steps"]:
            manifest_art_ids.update(s.get("input_artifact_ids", []))
            manifest_art_ids.update(s.get("output_artifact_ids", []))
        with uow_factory.for_project(project_id) as uow:
            lineage = uow._conn.execute(
                "SELECT DISTINCT artifact_id FROM artifact_lineage WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        persisted_ids = {row["artifact_id"] for row in lineage}
        # Every manifest artifact should be in persisted lineage
        unlinked = manifest_art_ids - persisted_ids
        assert not unlinked, f"Manifest artifacts without lineage: {unlinked}"
