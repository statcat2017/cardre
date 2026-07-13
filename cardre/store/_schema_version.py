"""Schema version checking and incremental migration runner."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from cardre.domain.errors import SchemaVersionError

if TYPE_CHECKING:
    pass

from cardre.store.schema import V2_STORE_SCHEMA_FAMILY, V2_STORE_SCHEMA_VERSION


def check_and_migrate(conn: sqlite3.Connection) -> None:
    """Verify schema family/version and run migrations if needed.

    Ensures ``store_meta`` exists, validates ``schema_family``, and runs
    incremental migrations from the stored version to the current version.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
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

    if stored_version > V2_STORE_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Store schema version {stored_version} is newer than app version "
            f"{V2_STORE_SCHEMA_VERSION}. Update the app to open this project."
        )

    if stored_version < V2_STORE_SCHEMA_VERSION:
        _run_migrations(conn, stored_version)
        conn.execute(
            "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_version', ?)",
            (str(V2_STORE_SCHEMA_VERSION),),
        )
        conn.commit()


def _run_migrations(conn: sqlite3.Connection, from_version: int) -> None:
    """Run incremental schema migrations from ``from_version`` to the
    current version.

    Each migration step takes a connection at version *N* and upgrades
    it to version *N+1*.  Steps run in order; a failure aborts with
    ``SchemaVersionError``.
    """
    migrations: dict[int, list[str]] = {
        100: [
            "ALTER TABLE runs ADD COLUMN active_step_id TEXT",
        ],
    }
    version = from_version
    while version < V2_STORE_SCHEMA_VERSION:
        statements = migrations.get(version)
        if statements is None:
            raise SchemaVersionError(
                f"No migration path from schema version {version} to "
                f"{V2_STORE_SCHEMA_VERSION}. Recreate this project with "
                f"the current app."
            )
        for sql in statements:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as exc:
                raise SchemaVersionError(
                    f"Migration {version}->{version + 1} failed: {sql}: {exc}"
                ) from exc
        version += 1
