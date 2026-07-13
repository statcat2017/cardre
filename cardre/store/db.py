"""SQLite connection management and transaction support for ProjectStore."""

from __future__ import annotations

import sqlite3
import threading
import types
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cardre._version import __version__
from cardre.domain.errors import SchemaVersionError
from cardre.store._locked_cursor import LockedCursor as _LockedCursor
from cardre.store._schema_version import check_and_migrate as _check_and_migrate
from cardre.store.schema import (
    ALL_TABLES_SQL,
    V2_STORE_SCHEMA_FAMILY,
    V2_STORE_SCHEMA_VERSION,
)


class ProjectStore:
    """SQLite-backed metadata store for a single Cardre v2 project.

    The project root is a directory (e.g. ``example.cardre/``) containing:
      - cardre.sqlite
      - datasets/
      - artifacts/
      - exports/
      - logs/
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._db: sqlite3.Connection | None = None
        self._txn_depth = 0
        # SQLite connections opened with check_same_thread=False are shared
        # across threads; every access must hold this lock to avoid
        # interleaved writes and corrupted transaction state.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Initialization / open
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create a fresh project store with the v2 schema.

        Hard-errors if the SQLite file already exists (call ``open()`` instead).
        """
        db_path = self.root / "cardre.sqlite"
        if db_path.exists():
            raise SchemaVersionError(
                f"Store already exists at {db_path}. Use open() to connect."
            )
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in ("datasets", "artifacts", "exports", "logs"):
            (self.root / sub).mkdir(exist_ok=True)

        conn = self._connect()
        conn.executescript(ALL_TABLES_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_family', ?)",
            (V2_STORE_SCHEMA_FAMILY,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_version', ?)",
            (str(V2_STORE_SCHEMA_VERSION),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('created_by_cardre_version', ?)",
            (__version__,),
        )
        conn.commit()

    def open(self) -> None:
        """Open an existing store and verify version compatibility.

        Hard-errors on:
        - missing ``store_meta`` table
        - ``schema_family != cardre-v2``
        - ``schema_version != 100``
        """
        db_path = self.root / "cardre.sqlite"
        if not db_path.exists():
            raise SchemaVersionError(
                f"No store found at {db_path}."
            )
        conn = self._connect()
        _check_and_migrate(conn)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._db is not None:
                return self._db
            db_path = self.root / "cardre.sqlite"
            conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            conn.isolation_level = None
            self._db = conn
            return conn

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def __enter__(self) -> ProjectStore:
        self.open()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: types.TracebackType | None) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Transaction
    # ------------------------------------------------------------------

    VALID_TXN_MODES = frozenset({"DEFERRED", "IMMEDIATE", "EXCLUSIVE"})

    @contextmanager
    def transaction(self, mode: str = "DEFERRED") -> Iterator[sqlite3.Connection]:
        """Context manager that yields a connection in an active transaction.

        Commits on success, rolls back on any exception.
        """
        with self._lock:
            if mode not in self.VALID_TXN_MODES:
                raise ValueError(
                    f"Invalid transaction mode {mode!r}; "
                    f"expected one of {sorted(self.VALID_TXN_MODES)}"
                )
            if self._txn_depth > 0:
                raise RuntimeError("nested transaction attempts are not supported")
            conn = self._connect()
            self._txn_depth += 1
            conn.execute(f"BEGIN {mode}")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                self._txn_depth -= 1

    # ------------------------------------------------------------------
    # Raw SQL helpers (for repos)
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | dict[str, Any] = ()) -> Any:
        with self._lock:
            return _LockedCursor(self._lock, self._connect().execute(sql, params))

    def artifact_path(self, artifact: Any) -> Path:
        """Resolve a stored artifact reference to an on-disk path."""
        if isinstance(artifact, str):
            path = Path(artifact)
        elif isinstance(artifact, dict):
            path = Path(artifact["path"])
        else:
            path = Path(artifact.path)
        return path if path.is_absolute() else self.root / path

    def execute_script(self, sql: str) -> None:
        with self._lock:
            self._connect().executescript(sql)

    def executemany(self, sql: str, seq: Iterable[tuple[Any, ...] | dict[str, Any]]) -> Any:
        with self._lock:
            return _LockedCursor(self._lock, self._connect().executemany(sql, seq))


