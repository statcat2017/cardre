"""Phase 1 — write/read the two-level evidence model; mixed role freshness
    is represented by separate edge rows with attached artifacts."""

import uuid

import pytest

from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
from cardre.store.db import ProjectStore


@pytest.fixture
def store_with_run(tmp_path):
    """Create a store with a basic run and plan version for evidence tests."""
    root = tmp_path / "evidence.cardre"
    store = ProjectStore(str(root))
    store.initialize()

    from cardre.store.plan_repo import PlanRepository
    from cardre.store.run_repo import RunRepository
    from cardre.store.project_repo import ProjectRepository

    plans = PlanRepository(store)
    runs = RunRepository(store)
    projects = ProjectRepository(store)

    project_id = projects.create("test")
    plan_id = plans.create_plan(project_id, "test_plan")
    pv_id = plans.create_version(plan_id)
    run_id = runs.create(pv_id)

    return store, pv_id, run_id


def test_insert_and_read_edge(store_with_run):
    """An evidence edge can be inserted and read back."""
    store, pv_id, run_id = store_with_run

    # Create a run step for the edge to reference
    rs_id = str(uuid.uuid4())
    source_rs_id = str(uuid.uuid4())

    from cardre.store.run_step_repo import RunStepRepository
    from cardre.domain.run import RunStep, RunStepStatus
    from cardre.domain.diagnostics import utc_now_iso

    rs_repo = RunStepRepository(store)
    now = utc_now_iso()
    run_step = RunStep(
        run_step_id=rs_id,
        run_id=run_id,
        step_id="step_b",
        plan_version_id=pv_id,
        status=RunStepStatus.PENDING,
        started_at=now,
    )
    rs_repo.save(run_step)

    # Also create a source run step
    source_step = RunStep(
        run_step_id=source_rs_id,
        run_id=run_id,
        step_id="step_a",
        plan_version_id=pv_id,
        status=RunStepStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
    )
    rs_repo.save(source_step)

    # Insert evidence edge
    from cardre.store.evidence_repo import EvidenceRepository

    evidence = EvidenceRepository(store)
    edge = EvidenceEdge(
        evidence_edge_id=str(uuid.uuid4()),
        run_id=run_id,
        run_step_id=rs_id,
        plan_version_id=pv_id,
        step_id="step_b",
        parent_step_id="step_a",
        source_run_id=run_id,
        source_run_step_id=source_rs_id,
        policy="run_only",
        source_label="run",
        is_reused=False,
        is_stale=False,
        stale_reason=None,
    )
    edge_id = evidence.insert_edge(edge)

    # Read back
    edges = evidence.get_edges_for_run_step(rs_id)
    assert len(edges) == 1
    assert edges[0].evidence_edge_id == edge_id
    assert edges[0].parent_step_id == "step_a"
    assert not edges[0].is_stale


def test_insert_and_read_artifact(store_with_run):
    """An evidence artifact can be inserted and read back."""
    store, pv_id, run_id = store_with_run

    from cardre.store.evidence_repo import EvidenceRepository
    from cardre.store.run_step_repo import RunStepRepository
    from cardre.store.artifact_repo import ArtifactRepository
    from cardre.domain.run import RunStep, RunStepStatus
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import utc_now_iso

    rs_repo = RunStepRepository(store)
    evidence = EvidenceRepository(store)
    artifacts = ArtifactRepository(store)
    now = utc_now_iso()

    # Create run step
    rs_id = str(uuid.uuid4())
    run_step = RunStep(
        run_step_id=rs_id, run_id=run_id, step_id="step_b",
        plan_version_id=pv_id, status=RunStepStatus.PENDING,
        started_at=now,
    )
    rs_repo.save(run_step)

    # Create source run step
    src_rs_id = str(uuid.uuid4())
    source_step = RunStep(
        run_step_id=src_rs_id, run_id=run_id, step_id="step_a",
        plan_version_id=pv_id, status=RunStepStatus.SUCCEEDED,
        started_at=now, finished_at=now,
    )
    rs_repo.save(source_step)

    # Register an artifact
    art = ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type="dataset",
        role="train",
        path="datasets/train.parquet",
        physical_hash="abc",
        logical_hash="def",
    )
    artifacts.register(art)

    # Insert edge
    edge = EvidenceEdge(
        evidence_edge_id=str(uuid.uuid4()),
        run_id=run_id, run_step_id=rs_id,
        plan_version_id=pv_id, step_id="step_b",
        parent_step_id="step_a",
        source_run_id=run_id, source_run_step_id=src_rs_id,
        policy="run_only", source_label="run",
        is_reused=False, is_stale=False,
    )
    edge_id = evidence.insert_edge(edge)

    # Insert artifact attached to edge
    ea = EvidenceArtifact(
        evidence_artifact_id=str(uuid.uuid4()),
        evidence_edge_id=edge_id,
        artifact_id=art.artifact_id,
        role="train",
    )
    evidence.insert_artifact(ea)

    # Read back
    artifacts_for_edge = evidence.get_artifacts_for_edge(edge_id)
    assert len(artifacts_for_edge) == 1
    assert artifacts_for_edge[0].artifact_id == art.artifact_id
    assert artifacts_for_edge[0].role == "train"

    artifacts_for_run_step = evidence.get_artifacts_for_run_step(rs_id)
    assert len(artifacts_for_run_step) == 1


def test_mixed_role_freshness_separate_edges(store_with_run):
    """Different freshness for different roles needs separate edges."""
    store, pv_id, run_id = store_with_run

    from cardre.store.evidence_repo import EvidenceRepository
    from cardre.store.run_step_repo import RunStepRepository
    from cardre.store.artifact_repo import ArtifactRepository
    from cardre.domain.run import RunStep, RunStepStatus
    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import utc_now_iso

    rs_repo = RunStepRepository(store)
    evidence = EvidenceRepository(store)
    artifacts = ArtifactRepository(store)
    now = utc_now_iso()

    # Steps
    rs_id = str(uuid.uuid4())
    run_step = RunStep(
        run_step_id=rs_id, run_id=run_id, step_id="step_c",
        plan_version_id=pv_id, status=RunStepStatus.PENDING,
        started_at=now,
    )
    rs_repo.save(run_step)

    src_rs_1 = str(uuid.uuid4())
    src_rs_2 = str(uuid.uuid4())
    for sid in [src_rs_1, src_rs_2]:
        rs_repo.save(RunStep(
            run_step_id=sid, run_id=run_id, step_id="step_parent",
            plan_version_id=pv_id, status=RunStepStatus.SUCCEEDED,
            started_at=now, finished_at=now,
        ))

    # Two artifacts (train and test)
    train_art = ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type="dataset", role="train",
        path="datasets/train.parquet",
        physical_hash="h1", logical_hash="h1",
    )
    test_art = ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type="dataset", role="test",
        path="datasets/test.parquet",
        physical_hash="h2", logical_hash="h2",
    )
    artifacts.register(train_art)
    artifacts.register(test_art)

    # Edge 1: train reused (is_reused=True, is_stale=False)
    edge1 = EvidenceEdge(
        evidence_edge_id=str(uuid.uuid4()),
        run_id=run_id, run_step_id=rs_id,
        plan_version_id=pv_id, step_id="step_c",
        parent_step_id="step_parent",
        source_run_id=run_id, source_run_step_id=src_rs_1,
        policy="run_only", source_label="run",
        is_reused=True, is_stale=False,
    )
    eid1 = evidence.insert_edge(edge1)
    evidence.insert_artifact(EvidenceArtifact(
        evidence_artifact_id=str(uuid.uuid4()),
        evidence_edge_id=eid1,
        artifact_id=train_art.artifact_id,
        role="train",
    ))

    # Edge 2: test stale (is_reused=False, is_stale=True)
    edge2 = EvidenceEdge(
        evidence_edge_id=str(uuid.uuid4()),
        run_id=run_id, run_step_id=rs_id,
        plan_version_id=pv_id, step_id="step_c",
        parent_step_id="step_parent",
        source_run_id=run_id, source_run_step_id=src_rs_2,
        policy="run_only", source_label="run",
        is_reused=False, is_stale=True,
        stale_reason="Params changed",
    )
    eid2 = evidence.insert_edge(edge2)
    evidence.insert_artifact(EvidenceArtifact(
        evidence_artifact_id=str(uuid.uuid4()),
        evidence_edge_id=eid2,
        artifact_id=test_art.artifact_id,
        role="test",
    ))

    # Read all edges for the run step
    edges = evidence.get_edges_for_run_step(rs_id)
    assert len(edges) == 2

    # Verify train edge
    train_edge = next(e for e in edges if e.is_reused)
    assert train_edge.is_stale is False
    train_arts = evidence.get_artifacts_for_edge(train_edge.evidence_edge_id)
    assert len(train_arts) == 1
    assert train_arts[0].role == "train"

    # Verify test edge (stale)
    stale_edge = next(e for e in edges if e.is_stale)
    assert stale_edge.stale_reason == "Params changed"
    test_arts = evidence.get_artifacts_for_edge(stale_edge.evidence_edge_id)
    assert len(test_arts) == 1
    assert test_arts[0].role == "test"

    # Combined view
    all_arts = evidence.get_artifacts_for_run_step(rs_id)
    assert len(all_arts) == 2
    roles = {a.role for a in all_arts}
    assert roles == {"train", "test"}
