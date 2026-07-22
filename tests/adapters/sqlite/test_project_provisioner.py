"""Tests for SqliteProjectProvisioner."""

from __future__ import annotations

import pytest

from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.domain.errors import CardreError


def test_provisioner_rejects_existing_root(tmp_path: pytest.TempPathFactory) -> None:
    """The target directory must not already exist."""
    root = tmp_path / "already-here"
    root.mkdir()
    sentinel = root / "sentinel.txt"
    sentinel.write_text("user data")

    provisioner = SqliteProjectProvisioner()
    with pytest.raises(CardreError, match="already exists") as excinfo:
        provisioner.initialize(root)

    assert excinfo.value.code == "STORE_ALREADY_EXISTS"
    # Unrelated files in the pre-existing directory must be untouched.
    assert sentinel.exists()


def test_provisioner_rejects_existing_project_sqlite(tmp_path: pytest.TempPathFactory) -> None:
    """A project.sqlite file is rejected (via the root-exists guard)."""
    root = tmp_path / "fresh"
    root.mkdir()
    db_path = root / "project.sqlite"
    db_path.write_text("not a real db")

    provisioner = SqliteProjectProvisioner()
    with pytest.raises(CardreError, match="already exists") as excinfo:
        provisioner.initialize(root)

    assert excinfo.value.code == "STORE_ALREADY_EXISTS"
    assert db_path.exists()


def test_provisioner_creates_directory_and_schema(tmp_path: pytest.TempPathFactory) -> None:
    """Happy path: a fresh project root is fully initialised."""
    root = tmp_path / "my-project.cardre"
    assert not root.exists()

    provisioner = SqliteProjectProvisioner()
    provisioner.initialize(root)

    assert root.is_dir()
    assert (root / "project.sqlite").is_file()
    assert (root / "objects").is_dir()
    assert (root / "manifests/runs").is_dir()
    assert (root / "exports").is_dir()

    import sqlite3
    conn = sqlite3.connect(str(root / "project.sqlite"))
    try:
        meta = dict(conn.execute("SELECT key, value FROM store_meta").fetchall())
    finally:
        conn.close()

    assert meta["schema_family"] == "cardre-v3"
    assert meta["schema_version"] == "1"
    assert "created_by_cardre_version" in meta
