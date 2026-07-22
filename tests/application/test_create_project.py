"""Tests for CreateProject use case."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cardre.application.projects.create_project import CreateProject
from cardre.domain.errors import CardreError

# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _FakeProvisioner:
    """Records the initiaization call but does not touch the filesystem."""

    def __init__(self) -> None:
        self.initialized_root: Path | None = None

    def initialize(self, root: Path) -> None:
        self.initialized_root = root
        root.mkdir(parents=True, exist_ok=True)


class _FakeRegistry:
    """In-memory project registry. Can be configured to fail on register."""

    def __init__(self, fail_on_register: bool = False) -> None:
        self._data: dict[str, str] = {}
        self._fail = fail_on_register

    def register(self, project_id: str, root: str | Path) -> None:
        if self._fail:
            raise CardreError("Registry write failed", code="REGISTRY_FAILURE")
        self._data[project_id] = str(Path(root).resolve())

    def resolve_root(self, project_id: str) -> Path | None:
        raw = self._data.get(project_id)
        return Path(raw).resolve() if raw else None

    def list_all(self) -> dict[str, str]:
        return dict(self._data)


class _FakeUoW:
    """In-memory UnitOfWork that stores projects in a shared store."""

    def __init__(self, store: dict) -> None:
        self._store = store
        self.committed = False
        self.rolled_back = False

    @property
    def projects(self) -> Any:
        from cardre.domain.project import Project

        class _ProjectRepo:
            def __init__(self, store: dict):
                self._store = store
            def create(self, name: str) -> str:
                import uuid
                pid = str(uuid.uuid4())
                self._store[pid] = {"project_id": pid, "name": name}
                return pid
            def get(self, project_id: str) -> Any:
                d = self._store.get(project_id)
                if d is None:
                    return None
                return Project(project_id=d["project_id"], name=d["name"], created_at="now", cardre_version="0.1")
            def list_all(self) -> list:
                return []
        return _ProjectRepo(self._store)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


class _FakeUoWFactory:
    """Returns ``_FakeUoW`` instances sharing the same project store."""

    def __init__(self) -> None:
        self._store: dict = {}

    def for_root(self, root: Path) -> _FakeUoW:
        return _FakeUoW(self._store)

    def for_project(self, project_id: str) -> _FakeUoW:
        return _FakeUoW(self._store)

    def read_only(self, project_id: str) -> _FakeUoW:
        return _FakeUoW(self._store)

    def for_root_readonly(self, root: Path) -> _FakeUoW:
        return _FakeUoW(self._store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_project_happy_path(tmp_path: Path) -> None:
    path = str(tmp_path / "test.cardre")
    use_case = CreateProject(
        provisioner=_FakeProvisioner(),
        registry=_FakeRegistry(),
        uow_factory=_FakeUoWFactory(),
    )
    project = use_case(name="Test project", path=path)
    assert project.name == "Test project"
    assert project.project_id is not None


def test_create_project_rejects_relative_path() -> None:
    use_case = CreateProject(
        provisioner=_FakeProvisioner(),
        registry=_FakeRegistry(),
        uow_factory=_FakeUoWFactory(),
    )
    with pytest.raises(CardreError, match="must be absolute") as excinfo:
        use_case(name="Bad", path="relative/path")
    assert excinfo.value.code == "INVALID_PROJECT_PATH"


def test_create_project_rejects_path_traversal() -> None:
    use_case = CreateProject(
        provisioner=_FakeProvisioner(),
        registry=_FakeRegistry(),
        uow_factory=_FakeUoWFactory(),
    )
    with pytest.raises(CardreError, match="not contain") as excinfo:
        use_case(name="Bad", path="/tmp/../etc")
    assert excinfo.value.code == "INVALID_PROJECT_PATH"


def test_compensation_removes_created_directory_on_registry_failure(tmp_path: Path) -> None:
    """When registry.register() fails, the newly-created project directory is
    removed. Since the provisioner rejects pre-existing directories, the entire
    root tree is safe to delete."""

    root = tmp_path / "test.cardre"
    assert not root.exists()

    use_case = CreateProject(
        provisioner=_FakeProvisioner(),
        registry=_FakeRegistry(fail_on_register=True),
        uow_factory=_FakeUoWFactory(),
    )

    with pytest.raises(CardreError, match="Registry write failed"):
        use_case(name="Test", path=str(root))

    # The directory must not exist after compensation.
    assert not root.exists()
