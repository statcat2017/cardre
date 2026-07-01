"""Phase 1 — opening a store with ``schema_family != cardre-v2`` raises
    ``SchemaVersionError`` (code ``STORE_VERSION_INCOMPATIBLE``)."""

import sqlite3

import pytest

from cardre.domain.errors import SchemaVersionError
from cardre.store.db import ProjectStore
from cardre.store.schema import (
    ALL_TABLES_SQL,
    V2_STORE_SCHEMA_FAMILY,
    V2_STORE_SCHEMA_VERSION,
)


def _create_store_with_meta(tmp_path, family: str, version: int):
    """Create a SQLite store with specific metadata values."""
    db_path = tmp_path / "cardre.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(ALL_TABLES_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_family', ?)",
        (family,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_version', ?)",
        (str(version),),
    )
    conn.commit()
    conn.close()
    return tmp_path


class TestRejectsV1Project:
    def test_rejects_v1_family(self, tmp_path):
        """schema_family == 'cardre.project_store.v2' (v1 family) is rejected."""
        _create_store_with_meta(tmp_path, "cardre.project_store.v2", 5)
        store = ProjectStore(str(tmp_path))
        with pytest.raises(SchemaVersionError) as exc:
            store.open()
        assert "STORE_VERSION_INCOMPATIBLE" in str(exc.value.code) or "STORE_VERSION_INCOMPATIBLE" in type(exc.value).__name__ or "STORE_VERSION_INCOMPATIBLE" in exc.value.code

    def test_rejects_wrong_family(self, tmp_path):
        """Random schema_family is rejected."""
        _create_store_with_meta(tmp_path, "some-other-app", 1)
        store = ProjectStore(str(tmp_path))
        with pytest.raises(SchemaVersionError):
            store.open()

    def test_rejects_wrong_version(self, tmp_path):
        """schema_version != 100 is rejected."""
        _create_store_with_meta(tmp_path, V2_STORE_SCHEMA_FAMILY, 99)
        store = ProjectStore(str(tmp_path))
        with pytest.raises(SchemaVersionError):
            store.open()

    def test_rejects_missing_meta(self, tmp_path):
        """Missing store_meta table raises SchemaVersionError."""
        db_path = tmp_path / "cardre.sqlite"
        conn = sqlite3.connect(str(db_path))
        # Create a project table without store_meta
        conn.execute("CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        store = ProjectStore(str(tmp_path))
        with pytest.raises(SchemaVersionError):
            store.open()

    def test_accepts_correct_family_and_version(self, tmp_path):
        """Correct schema_family + version opens without error."""
        _create_store_with_meta(tmp_path, V2_STORE_SCHEMA_FAMILY, V2_STORE_SCHEMA_VERSION)
        store = ProjectStore(str(tmp_path))
        store.open()  # should not raise

    def test_fresh_store_has_correct_meta(self, tmp_path):
        """Freshly initialized store has the right schema_family and version."""
        store_root = tmp_path / "fresh.cardre"
        store = ProjectStore(str(store_root))
        store.initialize()
        store.close()

        # Re-open and verify
        store2 = ProjectStore(str(store_root))
        store2.open()  # should not raise
        row = store2.execute(
            "SELECT value FROM store_meta WHERE key = 'schema_family'"
        ).fetchone()
        assert row["value"] == V2_STORE_SCHEMA_FAMILY
        row2 = store2.execute(
            "SELECT value FROM store_meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row2["value"] == str(V2_STORE_SCHEMA_VERSION)
        store2.close()
