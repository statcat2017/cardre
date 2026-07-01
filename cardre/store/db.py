"""SQLite connection management and transaction support for ProjectStore."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from cardre.domain.errors import SchemaVersionError
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
            ("0.2.0",),
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
        self._check_schema_version(conn)

    def _ensure_store_meta_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

    def _check_schema_version(self, conn: sqlite3.Connection) -> None:
        self._ensure_store_meta_table(conn)
        try:
            rows = conn.execute(
                "SELECT key, value FROM store_meta WHERE key IN ('schema_family', 'schema_version')"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise SchemaVersionError(
                "Store schema metadata is missing or corrupt. "
                "Recreate this project with the current app."
            ) from exc

        meta = {row["key"]: row["value"] for row in rows}
        family = meta.get("schema_family")
        if family != V2_STORE_SCHEMA_FAMILY:
            raise SchemaVersionError(
                f"Store schema family {family!r} does not match app family "
                f"{V2_STORE_SCHEMA_FAMILY!r}. Recreate this project with the current app."
            )

        version_text = meta.get("schema_version")
        if version_text is None:
            raise SchemaVersionError(
                "Store schema version is missing. Recreate this project with the current app."
            )

        try:
            stored_version = int(version_text)
        except ValueError as exc:
            raise SchemaVersionError(
                f"Store schema version {version_text!r} is invalid. "
                "Recreate this project with the current app."
            ) from exc

        if stored_version != V2_STORE_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Store schema version {stored_version} does not match app version "
                f"{V2_STORE_SCHEMA_VERSION}. Recreate this project with the current app."
            )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
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
        if self._db is not None:
            self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Transaction
    # ------------------------------------------------------------------

    VALID_TXN_MODES = frozenset({"DEFERRED", "IMMEDIATE", "EXCLUSIVE"})

    @contextmanager
    def transaction(self, mode: str = "DEFERRED"):
        """Context manager that yields a connection in an active transaction.

        Commits on success, rolls back on any exception.
        """
        if mode not in self.VALID_TXN_MODES:
            raise ValueError(
                f"Invalid transaction mode {mode!r}; "
                f"expected one of {sorted(self.VALID_TXN_MODES)}"
            )
        conn = self._connect()
        conn.execute(f"BEGIN {mode}")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Raw SQL helpers (for repos)
    # ------------------------------------------------------------------

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        return self._connect().execute(sql, params)

    def execute_script(self, sql: str) -> None:
        self._connect().executescript(sql)

    def executemany(self, sql: str, seq) -> sqlite3.Cursor:
        return self._connect().executemany(sql, seq)
