"""SQLite project provisioner — initializes a new project on disk."""

from __future__ import annotations

from pathlib import Path

from cardre._version import __version__
from cardre.adapters.sqlite.schema import (
    ALL_TABLES_SQL,
    V3_STORE_SCHEMA_FAMILY,
    V3_STORE_SCHEMA_VERSION,
)
from cardre.domain.errors import SchemaVersionError


class SqliteProjectProvisioner:
    """Creates a fresh project store at the given root path."""

    def initialize(self, root: Path) -> None:
        db_path = root / "project.sqlite"
        if db_path.exists():
            raise SchemaVersionError(
                f"Store already exists at {db_path}. Use open() to connect."
            )
        root.mkdir(parents=True, exist_ok=True)
        for sub in ("objects", "manifests/runs", "exports"):
            (root / sub).mkdir(parents=True, exist_ok=True)

        import sqlite3
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.isolation_level = None
        try:
            conn.executescript(ALL_TABLES_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_family', ?)",
                (V3_STORE_SCHEMA_FAMILY,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_version', ?)",
                (str(V3_STORE_SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('created_by_cardre_version', ?)",
                (__version__,),
            )
            conn.commit()
        finally:
            conn.close()
