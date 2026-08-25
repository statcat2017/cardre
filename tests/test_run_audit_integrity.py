"""Audit integrity tests — verifies post-run state after composed execution.

Asserts every step has evidence edges with evidence artifacts, no orphan
artifacts, manifest completeness, and edge provenance correctness.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.runs.submit_run import SubmitRunCommand
from cardre.bootstrap.container import build_container
from cardre.bootstrap.node_catalogue import build_default_catalogue
from cardre.bootstrap.settings import Settings
from tests.acceptance.fixture_pathway import build_acceptance_fixture_steps


def _write_input_parquet(path):
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


@pytest.fixture
def audit_run(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Audit")
        plan_id = uow.plans.create_plan(project_id, "Audit Plan")
        uow.commit()
    registry.register(project_id, root)

    parquet_path = _write_input_parquet(tmp_path / "input.parquet")
    cat = build_default_catalogue(Settings())
    steps = build_acceptance_fixture_steps(parquet_path, cat)

    with uow_factory.for_project(project_id) as uow:
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()

    settings = Settings(registry_path=str(tmp_path / "registry.json"))
    container = build_container(settings)
    result = container.submit_run_factory(project_id)(
        SubmitRunCommand(plan_version_id=pv_id, sync=True),
    )
    return project_id, plan_id, pv_id, result.run_id, uow_factory, root


class TestRunAuditIntegrity:
    def test_run_must_be_succeeded(self, audit_run):
        project_id, _, _, run_id, uow_factory, _ = audit_run
        with uow_factory.for_project(project_id) as uow:
            run = uow.runs.get(run_id)
        assert run is not None
        assert run.status == "succeeded", f"Run status: {run.status}"

    def test_every_step_has_evidence_edges_with_artifacts(self, audit_run):
        project_id, _, _, run_id, uow_factory, _ = audit_run
        with uow_factory.for_project(project_id) as uow:
            run_steps = uow.run_steps.get_for_run(run_id)
            for rs in run_steps:
                edges = uow.evidence.get_edges_for_run_step(rs.run_step_id)
                if rs.status.value == "succeeded" and rs.step_id not in ("import", "technical-manifest"):
                    assert len(edges) > 0, f"No evidence edges for step {rs.step_id}"
                    for edge in edges:
                        artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
                        assert len(artifacts) > 0, (
                            f"No evidence artifacts for edge {edge.evidence_edge_id} ({rs.step_id})"
                        )

    def test_manifest_has_steps_and_hashes(self, audit_run):
        _, _, _, run_id, _, root = audit_run
        manifest_path = root / "manifests" / "runs" / f"{run_id}.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest["steps"]) > 0
        assert manifest["manifest_hash"]
        assert manifest["pathway_hash"]

    def test_no_orphan_artifacts(self, audit_run):
        project_id, _, _, run_id, uow_factory, _ = audit_run
        with uow_factory.for_project(project_id) as uow:
            lineage = uow._conn.execute(
                "SELECT DISTINCT artifact_id FROM artifact_lineage WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            for row in lineage:
                art = uow.artifacts.get(row["artifact_id"])
                assert art is not None, f"Orphan artifact: {row['artifact_id']}"

    def test_evidence_edges_have_valid_sources(self, audit_run):
        project_id, _, _, run_id, uow_factory, _ = audit_run
        with uow_factory.for_project(project_id) as uow:
            edges = uow.evidence.get_edges_for_run(run_id)
            for edge in edges:
                source_rs = uow.run_steps.get(edge.source_run_step_id)
                assert source_rs is not None, f"Missing source run step: {edge.source_run_step_id}"
                assert source_rs.status.value == "succeeded", (
                    f"Source run step {edge.source_run_step_id} not succeeded: {source_rs.status}"
                )
