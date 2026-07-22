"""SQLite UnitOfWork — connection and transaction management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cardre.adapters.sqlite.project_repo import ProjectRepo
from cardre.application.ports.project_registry import ProjectRegistryPort
from cardre.application.ports.unit_of_work import UnitOfWork


class SqliteUnitOfWork:
    """SQLite-backed UnitOfWork for writes. Owns one connection + one IMMEDIATE transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._begun = False

    @property
    def projects(self) -> ProjectRepo:
        return ProjectRepo(self._conn)

    def commit(self) -> None:
        if self._begun:
            self._conn.commit()
            self._begun = False

    def rollback(self) -> None:
        if self._begun:
            self._conn.rollback()
            self._begun = False

    def close(self) -> None:
        if self._begun:
            self._conn.rollback()
            self._begun = False
        self._conn.close()

    def __enter__(self) -> UnitOfWork:
        self._conn.execute("BEGIN IMMEDIATE")
        self._begun = True
        return self

    def __exit__(self, *exc: object) -> None:
        if self._begun:
            if exc[0] is not None:
                self._conn.rollback()
            else:
                self._conn.commit()
            self._begun = False
        self._conn.close()


class SqliteReadOnlyUnitOfWork:
    """SQLite-backed UnitOfWork for reads only.

    Does NOT begin a transaction. Verifies the database file exists before
    connecting. Never commits. Uses read-only URI mode to prevent accidental
    database creation.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def projects(self) -> ProjectRepo:
        return ProjectRepo(self._conn)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(self, *exc: object) -> None:
        self._conn.close()


class SqliteUnitOfWorkFactory:
    """Creates write or read-only UnitOfWork instances for a given project."""

    def __init__(self, registry: ProjectRegistryPort) -> None:
        self._registry = registry

    def _open_conn(self, project_id: str) -> sqlite3.Connection:
        root = self._registry.resolve_root(project_id)
        if root is None:
            from cardre.domain.errors import CardreError
            raise CardreError(
                f"Project {project_id!r} not found",
                code="PROJECT_NOT_FOUND",
                context={"project_id": project_id},
            )
        db_path = root / "project.sqlite"
        if not db_path.exists():
            from cardre.domain.errors import CardreError
            raise CardreError(
                f"Project database not found at {db_path}",
                code="PROJECT_NOT_FOUND",
                context={"project_id": project_id, "path": str(db_path)},
            )
        conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
        return conn

    def _open_readonly_conn(self, db_path: Path) -> sqlite3.Connection:
        if not db_path.exists():
            from cardre.domain.errors import CardreError
            raise CardreError(
                f"Project database not found at {db_path}",
                code="PROJECT_NOT_FOUND",
                context={"path": str(db_path)},
            )
        uri = db_path.absolute().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, timeout=30, check_same_thread=False, uri=True)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
        return conn

    def for_project(self, project_id: str) -> UnitOfWork:
        conn = self._open_conn(project_id)
        return SqliteUnitOfWork(conn)

    def for_root(self, root: Path) -> UnitOfWork:
        db_path = root / "project.sqlite"
        if not db_path.exists():
            from cardre.domain.errors import CardreError
            raise CardreError(
                f"Project database not found at {db_path}",
                code="PROJECT_NOT_FOUND",
                context={"path": str(db_path)},
            )
        conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
        return SqliteUnitOfWork(conn)

    def read_only(self, project_id: str) -> UnitOfWork:
        root = self._registry.resolve_root(project_id)
        if root is None:
            from cardre.domain.errors import CardreError
            raise CardreError(
                f"Project {project_id!r} not found",
                code="PROJECT_NOT_FOUND",
                context={"project_id": project_id},
            )
        db_path = root / "project.sqlite"
        conn = self._open_readonly_conn(db_path)
        return SqliteReadOnlyUnitOfWork(conn)

    def for_root_readonly(self, root: Path) -> UnitOfWork:
        db_path = root / "project.sqlite"
        conn = self._open_readonly_conn(db_path)
        return SqliteReadOnlyUnitOfWork(conn)
