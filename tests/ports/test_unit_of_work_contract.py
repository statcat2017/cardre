"""UnitOfWork port contract tests (Batch 2A).

Runs the same lifecycle and transaction-semantics contract against both a
minimal in-memory fake and the real ``SqliteUnitOfWork`` /
``SqliteUnitOfWorkFactory`` backed by a provisioned project store. The fake is
a faithful, *minimal* implementation of the mutation boundary (eager
transaction, commit persists, rollback discards, close rolls back) so it does
not bypass the behaviour under test.
"""

from __future__ import annotations

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry


class _FakeProjects:
    def __init__(self, storage: dict[str, str]) -> None:
        self._storage = storage

    def create(self, name: str) -> str:
        project_id = f"proj-{len(self._storage) + 1}"
        self._storage[project_id] = name
        return project_id

    def get(self, project_id: str) -> str | None:
        return self._storage.get(project_id)

    def list_all(self) -> list[str]:
        return list(self._storage.values())


class _FakeTransaction:
    """Minimal UoW with real commit/rollback/close transaction semantics.

    Writes land in a pending overlay; ``commit()`` promotes them to the
    shared durable snapshot, while ``rollback()``/``close()`` without commit
    discard them. A fresh instance seeded with the snapshot observes only
    durable state.
    """

    def __init__(self, committed: dict[str, str]) -> None:
        self._committed = committed
        self._pending: dict[str, str] = dict(committed)
        self._closed = False

    @property
    def projects(self) -> _FakeProjects:
        if self._closed:
            raise RuntimeError("UnitOfWork is closed")
        return _FakeProjects(self._pending)

    def commit(self) -> None:
        if self._closed:
            raise RuntimeError("UnitOfWork has no open transaction to commit")
        self._committed.clear()
        self._committed.update(self._pending)
        self._closed = True

    def rollback(self) -> None:
        if self._closed:
            return
        self._pending = dict(self._committed)
        self._closed = True

    def close(self) -> None:
        if not self._closed:
            self._pending = dict(self._committed)
            self._closed = True

    def __enter__(self) -> _FakeTransaction:
        return self

    def __exit__(self, *exc: object) -> None:
        if exc[0] is None:
            self.commit()
        else:
            self.rollback()
        self.close()


class FakeFactory:
    """In-memory factory mirroring ``SqliteUnitOfWorkFactory`` (write + read)."""

    def __init__(self) -> None:
        self._committed: dict[str, str] = {}

    def for_project(self, project_id: str) -> _FakeTransaction:
        return _FakeTransaction(self._committed)

    def read_only(self, project_id: str) -> _FakeTransaction:
        return _FakeTransaction(self._committed)


def _real_factory(tmp_path) -> tuple[str, SqliteUnitOfWorkFactory]:
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        uow.commit()
    registry.register(project_id, root)
    return project_id, uow_factory


# Shared lifecycle contract exercised against both the fake and the real UoW.
# ``contract`` yields (factory, project_id) for each implementation; the same
# observable assertions then run against both.
#
# The shared parametrization deliberately covers only the repository-bound
# seams (``for_project`` / ``read_only``), which both implementations expose.
# ``for_root`` / ``for_root_readonly`` are real *provisioning* seams that
# initialise a project store on disk and only exist on the concrete
# ``SqliteUnitOfWorkFactory``; the fake has no store to provision. They are
# therefore intentionally tested real-only (see
# ``test_real_for_root_open_without_registry`` below) rather than forced into
# a shared contract that would have to fake away provisioning semantics.
@pytest.fixture(params=["fake", "real"])
def contract(request, tmp_path) -> tuple[object, str]:
    if request.param == "fake":
        return FakeFactory(), "fake"
    project_id, factory = _real_factory(tmp_path)
    return factory, project_id


def _project_names(projects) -> list[str]:
    """Extract names from a project listing regardless of return type.

    The fake exposes bare name strings; the real repo returns ``Project``
    domain objects. Normalising via ``.name`` keeps the shared assertions
    working against both without weakening the real contract.
    """
    return [p.name if hasattr(p, "name") else p for p in projects.list_all()]


def test_context_manager_commits_on_success(contract):
    factory, project_id = contract
    with factory.for_project(project_id) as uow:
        uow.projects.create("First")
    with factory.read_only(project_id) as ro:
        assert "First" in _project_names(ro.projects)


def test_context_manager_rolls_back_on_exception(contract):
    factory, project_id = contract
    with pytest.raises(RuntimeError, match="boom"):
        with factory.for_project(project_id) as uow:
            uow.projects.create("Discard")
            raise RuntimeError("boom")
    with factory.read_only(project_id) as ro:
        assert "Discard" not in _project_names(ro.projects)


def test_explicit_commit_persists(contract):
    factory, project_id = contract
    uow = factory.for_project(project_id)
    try:
        uow.projects.create("Persisted")
        uow.commit()
    finally:
        uow.close()
    with factory.read_only(project_id) as ro:
        assert "Persisted" in _project_names(ro.projects)


def test_rollback_discards(contract):
    factory, project_id = contract
    uow = factory.for_project(project_id)
    try:
        uow.projects.create("Gone")
        uow.rollback()
    finally:
        uow.close()
    with factory.read_only(project_id) as ro:
        assert "Gone" not in _project_names(ro.projects)


def test_close_without_commit_rolls_back(contract):
    factory, project_id = contract
    uow = factory.for_project(project_id)
    try:
        uow.projects.create("Uncommitted")
    finally:
        uow.close()
    with factory.read_only(project_id) as ro:
        assert "Uncommitted" not in _project_names(ro.projects)


def test_read_only_exposes_committed_state(contract):
    factory, project_id = contract
    uow = factory.for_project(project_id)
    try:
        uow.projects.create("Persisted")
        uow.commit()
    finally:
        uow.close()
    ro = factory.read_only(project_id)
    try:
        assert "Persisted" in _project_names(ro.projects)
    finally:
        ro.close()


def test_real_for_root_open_without_registry(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        uow.commit()
    # for_root_readonly opens the same database read-only without registry.
    with uow_factory.for_root_readonly(root) as ro:
        assert any(p.project_id == project_id for p in ro.projects.list_all())
