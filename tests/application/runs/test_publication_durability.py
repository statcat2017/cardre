"""Batch R2 — durable publication and terminal-state consistency proof tests.

Covers findings 1 (publication half) and 9 of the thermonuclear review:

1. **No orphan objects** — a step-persistence failure leaves no file in
   ``objects/`` without a durable artifact descriptor or pending-publication
   record, because files are moved out of staging only after the DB
   transaction commits.
2. **Manifest split-brain** — a manifest publish failure leaves a terminal
   run with a failed outbox record and no false published manifest; startup
   reconciliation republishes pending manifests idempotently and exactly once.

All tests run through the real SQLite adapter and the real filesystem
adapter, not fakes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.ports.artifact_store import StagedArtifact
from cardre.application.runs.finalize_run import FinalizeRun
from cardre.application.runs.reconcile_publications import ReconcilePublications
from cardre.domain.artifacts import json_logical_hash, physical_hash
from cardre.domain.run import RunStatus


class _FakeClock:
    def now_iso(self) -> str:
        return "2026-01-01T00:00:00Z"


class _FailingManifestPublisher:
    """Manifest publisher that raises before writing anything."""

    def publish(self, run_id: str, payload):
        raise OSError("injected manifest publish failure")


def _run_generation(uow_factory, project_id, run_id) -> int:
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None
    return run.worker_generation


def _provision(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "projects" / "p1"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps=[], is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING,
                            expected_from=(RunStatus.SUBMITTED, RunStatus.SUBMITTED))
        uow.runs.begin_worker_generation(run_id)
        uow.commit()
    registry.register(project_id, root)
    return project_id, plan_id, pv_id, run_id, uow_factory, registry, root


def _make_staged(root: Path, payload: bytes | None = None) -> StagedArtifact:
    staging_dir = root / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    if payload is None:
        payload = json.dumps({"a": 1}, sort_keys=True).encode("utf-8")
    staging = staging_dir / f"{physical_hash_from_bytes(payload)}.bin"
    staging.write_bytes(payload)
    return StagedArtifact(
        staging_path=staging,
        provisional_artifact_id=f"profile:report:{physical_hash(staging)}",
        physical_hash=physical_hash(staging),
        logical_hash=json_logical_hash(json.loads(payload)) if payload.startswith(b"{") else "",
        media_type="application/json",
        schema_version="profile_v1",
        role="report",
        artifact_type="profile_summary",
        metadata={"schema_version": "profile_v1"},
    )


def physical_hash_from_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Finding 1 — durable publication: no orphan object on step-persistence failure
# ---------------------------------------------------------------------------


def test_rollback_leaves_no_orphan_object(tmp_path):
    """A rollback after staging leaves no file in objects/ without a descriptor.

    Simulates the ExecuteRun step-persistence shape: stage an artifact, write
    the DB mutation (descriptor + outbox), then force a rollback. Because the
    file is only finalized (moved out of staging) after commit, a rollback
    must leave the file in staging, never in ``objects/``.
    """
    project_id, _plan_id, _pv_id, run_id, uow_factory, _registry, root = _provision(tmp_path)
    staged = _make_staged(root)
    store = FsArtifactStore(root)

    with uow_factory.for_project(project_id) as uow:
        # First mutation writes descriptor + outbox row.
        from cardre.domain.artifacts import ArtifactRef

        ref = ArtifactRef(
            artifact_id=staged.provisional_artifact_id,
            artifact_type=staged.artifact_type,
            role=staged.role,
            path=str(store.dest_path(staged)),
            physical_hash=staged.physical_hash,
            logical_hash=staged.logical_hash,
            media_type=staged.media_type,
            metadata=staged.metadata,
        )
        uow.artifacts.register(ref)
        uow.publications.enqueue_artifact(
            run_id=run_id,
            plan_version_id=_pv_id,
            run_step_id=f"{run_id}-s1",
            artifact_id=ref.artifact_id,
            physical_hash=staged.physical_hash,
            storage_key=str(store.object_path(staged.physical_hash)),
            staging_source=str(staged.staging_path),
        )
        uow.rollback()  # simulated failure before commit

    assert store.object_path(staged.physical_hash).exists() is False, (
        "object must not exist in objects/ after a rollback"
    )
    assert staged.staging_path.exists() is True, "staged file must remain in staging after rollback"


def test_finalize_moves_file_only_after_commit(tmp_path):
    """finalize() moves the staged file to objects/ (post-commit step)."""
    _project_id, _plan_id, _pv_id, _run_id, _uow_factory, _registry, root = _provision(tmp_path)
    staged = _make_staged(root)
    store = FsArtifactStore(root)

    assert store.object_path(staged.physical_hash).exists() is False
    dest = store.finalize(staged)
    assert dest == store.object_path(staged.physical_hash)
    assert dest.exists() is True
    assert staged.staging_path.exists() is False


def test_finalize_is_idempotent_for_duplicate_bytes(tmp_path):
    """finalize() keeps the existing object when bytes are duplicated."""
    _project_id, _plan_id, _pv_id, _run_id, _uow_factory, _registry, root = _provision(tmp_path)
    staged1 = _make_staged(root)
    store = FsArtifactStore(root)
    store.finalize(staged1)

    # Same bytes -> same object path.
    staged2 = _make_staged(root, payload=json.dumps({"a": 1}, sort_keys=True).encode("utf-8"))
    dest = store.finalize(staged2)
    assert dest == store.object_path(staged2.physical_hash)
    assert dest.exists() is True
    assert store.object_path(staged1.physical_hash) == store.object_path(staged2.physical_hash)


@pytest.mark.parametrize("fail_point", [
    "register", "run_steps.insert", "register_lineage", "evidence.insert_edge",
])
def test_step_failure_in_objects_dir_invariant(tmp_path, fail_point):
    """ExecuteRun-shaped persist sequence: a failure at any write point leaves
    no file in objects/ without a durable descriptor or pending outbox row.

    Mirrors the persist block of ``ExecuteRun``: stage a real file, write the
    mutation (descriptor, run step, lineage, evidence, outbox), then force a
    failure before commit. The file must remain in staging — never in
    ``objects/`` — because finalize only runs after the commit.
    """
    project_id, _plan_id, pv_id, run_id, uow_factory, _registry, root = _provision(tmp_path)
    staged = _make_staged(root)
    store = FsArtifactStore(root)

    from cardre.domain.artifacts import ArtifactRef
    from cardre.domain.diagnostics import utc_now_iso
    from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge
    from cardre.domain.run import RunStep, RunStepStatus

    run_step_id = f"{run_id}-s1"
    ref = ArtifactRef(
        artifact_id=staged.provisional_artifact_id,
        artifact_type=staged.artifact_type,
        role=staged.role,
        path=str(store.dest_path(staged)),
        physical_hash=staged.physical_hash,
        logical_hash=staged.logical_hash,
        media_type=staged.media_type,
        metadata=staged.metadata,
    )
    rs = RunStep(
        run_step_id=run_step_id, run_id=run_id, step_id="s1",
        plan_version_id=pv_id, status=RunStepStatus.SUCCEEDED,
        started_at=utc_now_iso(), finished_at=utc_now_iso(),
    )

    class _FailAfter:
        def __init__(self, callable, n):
            self._callable = callable
            self._remaining = n

        def __call__(self, *args, **kwargs):
            if self._remaining <= 0:
                raise RuntimeError("injected failure")
            self._remaining -= 1
            return self._callable(*args, **kwargs)

    uow = uow_factory.for_project(project_id)
    artifacts_repo = uow.artifacts
    run_steps_repo = uow.run_steps
    evidence_repo = uow.evidence
    try:
        if fail_point == "register":
            artifacts_repo.register = _FailAfter(artifacts_repo.register, 0)  # type: ignore[method-assign]
        elif fail_point == "run_steps.insert":
            run_steps_repo.insert = _FailAfter(run_steps_repo.insert, 0)  # type: ignore[method-assign]
        elif fail_point == "register_lineage":
            artifacts_repo.register_lineage = _FailAfter(artifacts_repo.register_lineage, 0)  # type: ignore[method-assign]
        elif fail_point == "evidence.insert_edge":
            evidence_repo.insert_edge = _FailAfter(evidence_repo.insert_edge, 0)  # type: ignore[method-assign]

        artifacts_repo.register(ref)
        uow.publications.enqueue_artifact(
            run_id=run_id, plan_version_id=pv_id, run_step_id=run_step_id,
            artifact_id=ref.artifact_id, physical_hash=staged.physical_hash,
            storage_key=str(store.object_path(staged.physical_hash)),
            staging_source=str(staged.staging_path),
        )
        run_steps_repo.insert(rs)
        artifacts_repo.register_lineage(
            run_id=run_id, run_step_id=run_step_id, plan_version_id=pv_id,
            step_id="s1", artifact_id=ref.artifact_id, direction="output",
        )
        evidence_repo.insert_edge(EvidenceEdge(
            evidence_edge_id="e1", run_id=run_id, run_step_id=run_step_id,
            plan_version_id=pv_id, step_id="s1", parent_step_id="s0",
            source_run_id=run_id, source_run_step_id=run_step_id,
            policy="exact", source_label="test", is_reused=False, is_stale=False,
        ))
        evidence_repo.insert_artifact(EvidenceArtifact(
            evidence_artifact_id="ea1", evidence_edge_id="e1",
            artifact_id=ref.artifact_id, role="report",
        ))
        uow.commit()
    except RuntimeError as exc:
        assert "injected failure" in str(exc)
        uow.rollback()
    finally:
        uow.close()

    # Invariant: no object file without a durable descriptor or pending row.
    assert store.object_path(staged.physical_hash).exists() is False, (
        f"failure at {fail_point} must not leave an object in objects/"
    )
    assert staged.staging_path.exists() is True, "staged file must remain in staging"
    with uow_factory.read_only(project_id) as ro:
        assert ro.artifacts.get(ref.artifact_id) is None
        assert ro.run_steps.get(run_step_id) is None
        assert ro.artifacts.artifacts_for_run_step(run_step_id) == []
        assert ro.publications.list_by_run(run_id) == []


# ---------------------------------------------------------------------------
# Finding 9 — manifest / terminal-state split-brain
# ---------------------------------------------------------------------------


def test_manifest_publish_failure_leaves_terminal_run_and_failed_outbox(tmp_path):
    """Force the manifest publisher to fail. The DB run must be terminal with a
    failed outbox record and no false published manifest."""
    project_id, _plan_id, pv_id, run_id, uow_factory, _registry, _root = _provision(tmp_path)
    failing = _FailingManifestPublisher()
    finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), failing, _FakeClock())

    with pytest.raises(OSError, match="injected manifest publish failure"):
        finalize(run_id, "succeeded", worker_generation=_run_generation(uow_factory, project_id, run_id))

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        assert str(run.status) == "succeeded", "run must be terminal despite publish failure"
        rows = uow.publications.list_by_run(run_id)
        assert len(rows) == 1
        assert rows[0]["kind"] == "manifest"
        assert rows[0]["state"] == "failed"
        assert "injected" in rows[0]["error"]

    # No manifest was published by the failing publisher.
    publisher = FsManifestPublisher(_root)
    assert publisher.read(run_id) is None


def test_reconciliation_republishes_pending_manifest(tmp_path):
    """Reconciliation republishes a pending manifest exactly once and marks the
    outbox row published, and the run/manifest hashes agree."""
    project_id, _plan_id, pv_id, run_id, uow_factory, registry, root = _provision(tmp_path)
    publisher = FsManifestPublisher(root)

    # Simulate a crash between the DB commit and the filesystem publish:
    # enqueue the manifest outbox row and leave it pending (no publish).
    from cardre.domain.manifest import compute_manifest_hash, compute_pathway_hash

    payload = {
        "manifest_version": "cardre.run_manifest.v1",
        "run_id": run_id,
        "plan_version_id": pv_id,
        "status": "succeeded",
        "steps": [],
        "pathway_hash": "",
    }
    payload["pathway_hash"] = compute_pathway_hash(payload["steps"])
    payload["manifest_hash"] = compute_manifest_hash(payload)
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(run_id, RunStatus.SUCCEEDED,
                            expected_from=(RunStatus.RUNNING,))
        outbox_id = uow.publications.enqueue_manifest(
            run_id=run_id, plan_version_id=pv_id, payload=payload,
            manifest_hash=payload["manifest_hash"],
        )
        uow.commit()

    assert publisher.read(run_id) is None, "precondition: manifest not yet published"

    reconcile = ReconcilePublications(
        uow_factory,
        registry,
        lambda pid: FsArtifactStore(root),
        lambda pid: FsManifestPublisher(root),
    )
    outcome = reconcile()
    assert outcome.published == 1
    assert outcome.failed == 0

    data = publisher.read(run_id)
    assert data is not None, "manifest must be published after reconciliation"
    assert data["run_id"] == run_id
    from cardre.domain.manifest import compute_manifest_hash

    assert data["manifest_hash"] == compute_manifest_hash(data)

    with uow_factory.read_only(project_id) as uow:
        row = uow.publications.get(outbox_id)
        assert row["state"] == "published"
        run = uow.runs.get(run_id)
        assert str(run.status) == "succeeded"


def test_reconciliation_is_idempotent(tmp_path):
    """Running reconciliation twice publishes exactly one manifest."""
    project_id, _plan_id, pv_id, run_id, uow_factory, registry, root = _provision(tmp_path)
    publisher = FsManifestPublisher(root)

    from cardre.domain.manifest import compute_manifest_hash, compute_pathway_hash

    payload = {
        "manifest_version": "cardre.run_manifest.v1",
        "run_id": run_id,
        "plan_version_id": pv_id,
        "status": "succeeded",
        "steps": [],
        "pathway_hash": "",
    }
    payload["pathway_hash"] = compute_pathway_hash(payload["steps"])
    payload["manifest_hash"] = compute_manifest_hash(payload)
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(run_id, RunStatus.SUCCEEDED,
                            expected_from=(RunStatus.RUNNING,))
        uow.publications.enqueue_manifest(
            run_id=run_id, plan_version_id=pv_id, payload=payload,
            manifest_hash=payload["manifest_hash"],
        )
        uow.commit()

    reconcile = ReconcilePublications(
        uow_factory,
        registry,
        lambda pid: FsArtifactStore(root),
        lambda pid: FsManifestPublisher(root),
    )
    first = reconcile()
    second = reconcile()

    assert first.published == 1
    assert second.published == 0, "second pass must find nothing pending"
    data = publisher.read(run_id)
    assert data is not None and data["status"] == "succeeded"

    with uow_factory.read_only(project_id) as uow:
        rows = uow.publications.list_by_run(run_id)
        assert all(r["state"] == "published" for r in rows)


def test_failed_manifest_outbox_reconciled_with_working_publisher(tmp_path):
    """A previously-failed manifest publication is retried by reconciliation."""
    project_id, _plan_id, pv_id, run_id, uow_factory, registry, root = _provision(tmp_path)
    failing = _FailingManifestPublisher()
    finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), failing, _FakeClock())

    with pytest.raises(OSError):
        finalize(run_id, "succeeded", worker_generation=_run_generation(uow_factory, project_id, run_id))

    reconcile = ReconcilePublications(
        uow_factory,
        registry,
        lambda pid: FsArtifactStore(root),
        lambda pid: FsManifestPublisher(root),
    )
    outcome = reconcile()
    assert outcome.published == 1

    publisher = FsManifestPublisher(root)
    assert publisher.read(run_id) is not None
    assert publisher.read(run_id)["status"] == "succeeded"

    with uow_factory.read_only(project_id) as uow:
        rows = uow.publications.list_by_run(run_id)
        assert all(r["state"] == "published" for r in rows)
