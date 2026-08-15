from __future__ import annotations

import uuid

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge


@pytest.fixture
def provisioned(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, is_committed=True)
        uow.commit()
    registry.register(project_id, root)
    return project_id, pv_id, uow_factory


def test_evidence_edges_and_artifacts_round_trip(provisioned) -> None:
    project_id, pv_id, uow_factory = provisioned
    now = utc_now_iso()

    with uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(pv_id)
        uow.commit()

        from cardre.domain.run import RunStep, RunStepStatus
        uow.run_steps.insert(RunStep(
            run_step_id="rs-1",
            run_id=run_id,
            step_id="step-1",
            plan_version_id=pv_id,
            status=RunStepStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
            execution_fingerprint={},
            warnings=[],
            errors=[],
        ))
        uow.commit()

        edge = EvidenceEdge(
            evidence_edge_id=str(uuid.uuid4()),
            run_id=run_id,
            run_step_id="rs-1",
            plan_version_id=pv_id,
            step_id="step-1",
            parent_step_id="step-0",
            source_run_id=run_id,
            source_run_step_id="rs-1",
            policy="exact",
            source_label="parent",
            is_reused=False,
            is_stale=False,
            created_at=now,
        )
        uow.evidence.insert_edge(edge)
        from cardre.domain.artifacts import ArtifactRef
        uow.artifacts.register(ArtifactRef(
            artifact_id="art-1",
            artifact_type="bin_definition",
            role="bin_definition",
            path="/tmp/art-1.json",
            physical_hash="ph",
            logical_hash="lh",
            media_type="application/json",
            metadata={"schema_version": "cardre.bin_definition.v1"},
        ))
        uow.evidence.insert_artifact(EvidenceArtifact(
            evidence_artifact_id=str(uuid.uuid4()),
            evidence_edge_id=edge.evidence_edge_id,
            artifact_id="art-1",
            role="bin_definition",
            created_at=now,
        ))
        uow.commit()

        edges = uow.evidence.get_edges_for_plan_step(pv_id, "step-1")
        assert len(edges) == 1

        edge = edges[0]
        artifacts = uow.evidence.get_artifacts_for_edge(edge.evidence_edge_id)
        assert len(artifacts) == 1
        assert artifacts[0].evidence_edge_id == edge.evidence_edge_id
        assert artifacts[0].role == "bin_definition"

        run_step_artifacts = uow.evidence.get_artifacts_for_run_step(edge.run_step_id)
        assert [artifact.artifact_id for artifact in run_step_artifacts] == [
            artifacts[0].artifact_id,
        ]
