"""Unit of work port — transaction boundary for persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from cardre.domain.project import Project


@runtime_checkable
class ProjectRepoPort(Protocol):
    """Query handle for the projects table."""

    def create(self, name: str) -> str: ...

    def get(self, project_id: str) -> Project | None: ...

    def list_all(self) -> list[Project]: ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Owns a single connection and transaction. Commit on success, rollback on exception."""

    @property
    def conn(self) -> object:  # sqlite3.Connection in the SQLite adapter
        ...

    @property
    def projects(self) -> ProjectRepoPort: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, *exc: object) -> None: ...


@runtime_checkable
class UnitOfWorkFactory(Protocol):
    """Creates UnitOfWork instances for a given project."""

    def for_project(self, project_id: str) -> UnitOfWork: ...

    def for_root(self, root: Path) -> UnitOfWork: ...

    def read_only(self, project_id: str) -> UnitOfWork: ...
