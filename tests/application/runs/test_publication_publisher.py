"""PublicationPublisher — protocol contract tests.

Proves the post-commit publication protocol owned by ``PublicationPublisher``
using compact fakes for the UoW and the writer:

- The writer runs before the outbox transition.
- Writer success → exactly one ``mark_published``.
- Writer failure → exactly one ``mark_failed`` with the error string, then
  re-raise.
- A failing mark transition is rolled back and closed.
- The original writer exception is preserved even if recording failure also
  errors.
- Artifact and manifest publication share one implementation (the same
  ``publish`` call carries any writer).

Two integration tests exercise the real SQLite + filesystem adapters to prove
the seam composes with production adapters.
"""

from __future__ import annotations

import json

import pytest

from cardre.application.publications.publisher import PublicationPublisher


class _FakePublications:
    def __init__(self) -> None:
        self.published: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def mark_published(self, outbox_id: str) -> None:
        self.published.append(outbox_id)

    def mark_failed(self, outbox_id: str, error: str) -> None:
        self.failed.append((outbox_id, error))


class _FakeUoW:
    def __init__(self, publications: _FakePublications | None = None) -> None:
        self.publications = publications or _FakePublications()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _FakeUoWFactory:
    def __init__(self, uow: _FakeUoW) -> None:
        self._uow = uow
        self.opened = 0

    def __call__(self) -> _FakeUoW:
        self.opened += 1
        return self._uow


def _publisher(uow: _FakeUoW) -> tuple[PublicationPublisher, _FakeUoWFactory]:
    factory = _FakeUoWFactory(uow)
    return PublicationPublisher(factory), factory


# ---------------------------------------------------------------------------
# Protocol contract — writer runs before the transition
# ---------------------------------------------------------------------------


def test_writer_runs_before_outbox_transition():
    uow = _FakeUoW()
    publisher, _ = _publisher(uow)
    order: list[str] = []

    def writer():
        order.append("write")

    publisher.publish("o1", writer)

    assert order == ["write"]
    assert uow.publications.published == ["o1"]
    assert uow.publications.failed == []
    assert uow.committed is True
    assert uow.closed is True


def test_writer_success_marks_exactly_once():
    uow = _FakeUoW()
    publisher, _ = _publisher(uow)
    publisher.publish("o1", lambda: None)
    publisher.publish("o2", lambda: None)

    assert uow.publications.published == ["o1", "o2"]
    assert uow.publications.failed == []


# ---------------------------------------------------------------------------
# Failure protocol
# ---------------------------------------------------------------------------


def test_writer_failure_marks_failed_once_and_reraises():
    uow = _FakeUoW()
    publisher, _ = _publisher(uow)

    def writer():
        raise RuntimeError("injected writer failure")

    with pytest.raises(RuntimeError, match="injected writer failure"):
        publisher.publish("o1", writer)

    assert uow.publications.failed == [("o1", "injected writer failure")]
    assert uow.publications.published == []
    assert uow.committed is True, "mark_failed transaction must commit"
    assert uow.closed is True


def test_mark_transaction_rolled_back_and_closed_on_mark_failure():
    """If mark_published itself raises, the mark UoW is rolled back and closed,
    and the publisher does not mask the failure."""
    publications = _FakePublications()

    def _boom_mark(outbox_id):
        raise RuntimeError("injected mark failure")

    publications.mark_published = _boom_mark  # type: ignore[method-assign]
    uow = _FakeUoW(publications)
    publisher, _ = _publisher(uow)

    with pytest.raises(RuntimeError, match="injected mark failure"):
        publisher.publish("o1", lambda: None)

    assert uow.rolled_back is True
    assert uow.closed is True
    assert uow.publications.published == []


def test_original_writer_exception_preserved_when_mark_failed_errors():
    """If the writer raises and mark_failed also raises, the writer's exception
    is preserved (it propagates from the ``except`` block)."""
    publications = _FakePublications()

    def _boom_mark(outbox_id, error):
        raise OSError("injected mark_failed failure")

    publications.mark_failed = _boom_mark  # type: ignore[method-assign]
    uow = _FakeUoW(publications)
    publisher, _ = _publisher(uow)

    def writer():
        raise ValueError("writer exploded")

    with pytest.raises(ValueError, match="writer exploded"):
        publisher.publish("o1", writer)


def test_artifact_and_manifest_share_one_implementation():
    """A single ``publish`` call carries any writer — artifact finalize and
    manifest write are the same protocol, not two method copies."""
    uow = _FakeUoW()
    publisher, _ = _publisher(uow)
    calls: list[str] = []

    publisher.publish("a", lambda: calls.append("finalize"))
    publisher.publish("m", lambda: calls.append("publish"))

    assert calls == ["finalize", "publish"]
    assert uow.publications.published == ["a", "m"]


# ---------------------------------------------------------------------------
# Integration — the seam composes with real adapters
# ---------------------------------------------------------------------------


def test_integration_publish_artifact_with_real_adapters(tmp_path):
    """publish(outbox_id, lambda: artifact_store.finalize(staged)) moves the
    staged file to objects/ and marks the row published, through the real
    SQLite adapter."""
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    from cardre.adapters.system.project_registry import JsonProjectRegistry
    from cardre.application.ports.artifact_store import StagedArtifact
    from cardre.domain.artifacts import json_logical_hash, physical_hash

    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps=[], is_committed=True)
        uow.commit()
    registry.register(project_id, root)

    staging_dir = root / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"a": 1}, sort_keys=True).encode("utf-8")
    staging = staging_dir / "artifact.bin"
    staging.write_bytes(payload)
    staged = StagedArtifact(
        staging_path=staging,
        provisional_artifact_id=f"profile:report:{physical_hash(staging)}",
        physical_hash=physical_hash(staging),
        logical_hash=json_logical_hash({"a": 1}),
        media_type="application/json",
        schema_version="profile_v1",
        role="report",
        artifact_type="profile_summary",
        metadata={"schema_version": "profile_v1"},
    )

    store = FsArtifactStore(root)
    from cardre.domain.artifacts import ArtifactRef

    with uow_factory.for_project(project_id) as uow:
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
        outbox_id = uow.publications.enqueue_artifact(
            run_id="",
            plan_version_id=pv_id,
            run_step_id="",
            artifact_id=ref.artifact_id,
            physical_hash=staged.physical_hash,
            storage_key=str(store.object_path(staged.physical_hash)),
            staging_source=str(staged.staging_path),
        )
        uow.commit()

    publisher = PublicationPublisher(lambda: uow_factory.for_project(project_id))
    publisher.publish(outbox_id, lambda: store.finalize(staged))

    assert store.object_path(staged.physical_hash).exists()
    with uow_factory.read_only(project_id) as uow:
        row = uow.publications.get(outbox_id)
    assert row["state"] == "published"


def test_integration_publish_manifest_with_real_adapters(tmp_path):
    """publish(outbox_id, lambda: manifest_publisher.publish(run_id, payload))
    writes the manifest and marks the row published, through the real SQLite
    adapter."""
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
    from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
    from cardre.adapters.system.project_registry import JsonProjectRegistry
    from cardre.domain.run import RunStatus

    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps=[], is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING,
                            expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    registry.register(project_id, root)

    payload = {"run_id": run_id, "plan_version_id": pv_id, "status": "succeeded", "steps": []}
    with uow_factory.for_project(project_id) as uow:
        outbox_id = uow.publications.enqueue_manifest(
            run_id=run_id, plan_version_id=pv_id, payload=payload,
            manifest_hash=payload.get("manifest_hash", ""),
        )
        uow.commit()

    manifest_publisher = FsManifestPublisher(root)
    publisher = PublicationPublisher(lambda: uow_factory.for_project(project_id))
    publisher.publish(outbox_id, lambda: manifest_publisher.publish(run_id, payload))

    assert manifest_publisher.manifest_path(run_id).exists()
    with uow_factory.read_only(project_id) as uow:
        row = uow.publications.get(outbox_id)
    assert row["state"] == "published"
