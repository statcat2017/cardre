"""Slice 1 — ReconcilePublications must surface a per-Project pending-read
failure instead of silently skipping the Project.

A corrupted or unreadable Project database must not make startup reconciliation
silently drop that Project's pending publication work. Reconciliation must
continue to the remaining Projects and expose an observable failed outcome for
the unreadable Project, without falsely claiming its pending rows were
published.

Tests use the real SQLite/filesystem Adapters and a small fake only at the
``uow_factory`` seam, where the test needs a controlled per-Project read
failure.
"""

from __future__ import annotations

from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.publications.publisher import PublicationPublisher
from cardre.application.runs.reconcile_publications import ReconcilePublications
from cardre.domain.manifest import compute_manifest_hash, compute_pathway_hash
from cardre.domain.run import RunStatus


class _FailingReadUoWFactory:
    """Wrapper that raises on ``read_only`` for one Project and delegates to the
    real factory otherwise. This is the existing ``uow_factory`` seam."""

    def __init__(self, real, fail_project_id: str) -> None:
        self._real = real
        self._fail_project_id = fail_project_id

    def read_only(self, project_id: str):
        if project_id == self._fail_project_id:
            raise RuntimeError("injected pending publication read failure")
        return self._real.read_only(project_id)

    def for_project(self, project_id: str):
        return self._real.for_project(project_id)


def _publisher(uow_factory, project_id) -> PublicationPublisher:
    return PublicationPublisher(lambda: uow_factory.for_project(project_id))


def _provision(tmp_path):
    """Provision one real Project with a pending manifest, and register a second
    (failing) Project id first so reconciliation must skip past it."""
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "projects" / "p1"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        good_project_id = uow.projects.create("Good Project")
        plan_id = uow.plans.create_plan(good_project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps=[], is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING,
                            expected_from=(RunStatus.SUBMITTED,))
        uow.runs.transition(run_id, RunStatus.SUCCEEDED,
                            expected_from=(RunStatus.RUNNING,))
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
        uow.publications.enqueue_manifest(
            run_id=run_id, plan_version_id=pv_id, payload=payload,
            manifest_hash=payload["manifest_hash"],
        )
        uow.commit()

    # Failing Project registered first so reconciliation must continue past it.
    registry.register("failing-project", root)
    registry.register(good_project_id, root)
    return good_project_id, run_id, uow_factory, registry, root


def test_reconcile_continues_and_records_project_read_failure(tmp_path):
    """A per-Project pending-read failure is recorded and does not block or
    falsely publish other Projects."""
    good_project_id, run_id, uow_factory, registry, root = _provision(tmp_path)
    failing = _FailingReadUoWFactory(uow_factory, "failing-project")

    reconcile = ReconcilePublications(
        failing,
        registry,
        lambda pid: _publisher(uow_factory, pid),
        lambda pid: FsArtifactStore(root),
        lambda pid: FsManifestPublisher(root),
    )
    outcome = reconcile()

    # The good Project's pending manifest was still published.
    assert outcome.published == 1, f"expected one published manifest: {outcome.results}"
    publisher = FsManifestPublisher(root)
    assert publisher.read(run_id) is not None

    # The failing Project surfaced an observable failure instead of silence.
    failed = [r for r in outcome.results if r.project_id == "failing-project"]
    assert len(failed) == 1, f"expected one failed project result: {outcome.results}"
    assert failed[0].state == "failed"
    assert "injected pending publication read failure" in failed[0].error
    assert good_project_id in {r.project_id for r in outcome.results}

    # No false claim that the failing Project's rows were published.
    assert not any(
        r.project_id == "failing-project" and r.state == "published"
        for r in outcome.results
    )
