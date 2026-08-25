"""Tests for store_meta schema-identity validation on connection open.

The store retains one schema identifier and rejects incompatible project
stores (ADR-0015). Every writable and read-only open path must validate
``store_meta`` and raise ``STORE_VERSION_INCOMPATIBLE`` on a missing or
mismatched identity, with recreate-project context. No migration chain is
provided; projects are recreated.
"""

from __future__ import annotations

import sqlite3

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.sqlite.schema import (
    STORE_SCHEMA_FAMILY,
    STORE_SCHEMA_VERSION,
)
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.domain.errors import CardreError


def _provision(tmp_path):
    """Provision a real project and return (project_id, uow_factory, root)."""
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        uow.commit()
    registry.register(project_id, root)
    return project_id, uow_factory, root


def _set_store_meta(root, family, version):
    """Overwrite the store_meta identity to simulate an old/incompatible store."""
    db_path = root / "project.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM store_meta")
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('schema_family', ?)",
            (family,),
        )
        conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
        conn.commit()
    finally:
        conn.close()


def _assert_incompatible(excinfo, root):
    err = excinfo.value
    assert isinstance(err, CardreError)
    assert err.code == "STORE_VERSION_INCOMPATIBLE"
    assert "recreate" in err.message.lower()
    assert err.context["path"] == str(root / "project.sqlite")


# ---------------------------------------------------------------------------
# Current metadata opens
# ---------------------------------------------------------------------------


def test_current_metadata_opens_writable(tmp_path):
    project_id, uow_factory, _root = _provision(tmp_path)
    with uow_factory.for_project(project_id) as uow:
        assert uow.plans.list_for_project(project_id) == []


def test_current_metadata_opens_readonly(tmp_path):
    project_id, uow_factory, _root = _provision(tmp_path)
    with uow_factory.read_only(project_id) as ro:
        assert ro.plans.list_for_project(project_id) == []


def test_current_metadata_opens_for_root(tmp_path):
    _project_id, uow_factory, root = _provision(tmp_path)
    with uow_factory.for_root(root) as uow:
        assert uow.projects is not None


def test_current_metadata_opens_for_root_readonly(tmp_path):
    _project_id, uow_factory, root = _provision(tmp_path)
    with uow_factory.for_root_readonly(root) as ro:
        assert ro.projects is not None


# ---------------------------------------------------------------------------
# Old cardre-v3 / version-1 metadata is rejected
# ---------------------------------------------------------------------------


def test_old_family_rejected_writable(tmp_path):
    project_id, uow_factory, root = _provision(tmp_path)
    _set_store_meta(root, "cardre-v3", STORE_SCHEMA_VERSION)
    with pytest.raises(CardreError) as excinfo:
        uow_factory.for_project(project_id)
    _assert_incompatible(excinfo, root)


def test_old_family_rejected_readonly(tmp_path):
    project_id, uow_factory, root = _provision(tmp_path)
    _set_store_meta(root, "cardre-v3", STORE_SCHEMA_VERSION)
    with pytest.raises(CardreError) as excinfo:
        uow_factory.read_only(project_id)
    _assert_incompatible(excinfo, root)


def test_old_family_rejected_for_root(tmp_path):
    _project_id, uow_factory, root = _provision(tmp_path)
    _set_store_meta(root, "cardre-v3", STORE_SCHEMA_VERSION)
    with pytest.raises(CardreError) as excinfo:
        uow_factory.for_root(root)
    _assert_incompatible(excinfo, root)


def test_old_family_rejected_for_root_readonly(tmp_path):
    _project_id, uow_factory, root = _provision(tmp_path)
    _set_store_meta(root, "cardre-v3", STORE_SCHEMA_VERSION)
    with pytest.raises(CardreError) as excinfo:
        uow_factory.for_root_readonly(root)
    _assert_incompatible(excinfo, root)


# ---------------------------------------------------------------------------
# Missing metadata is rejected
# ---------------------------------------------------------------------------


def test_missing_metadata_rejected_writable(tmp_path):
    project_id, uow_factory, root = _provision(tmp_path)
    db_path = root / "project.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM store_meta")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(CardreError) as excinfo:
        uow_factory.for_project(project_id)
    _assert_incompatible(excinfo, root)


def test_missing_metadata_rejected_readonly(tmp_path):
    project_id, uow_factory, root = _provision(tmp_path)
    db_path = root / "project.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM store_meta")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(CardreError) as excinfo:
        uow_factory.read_only(project_id)
    _assert_incompatible(excinfo, root)


# ---------------------------------------------------------------------------
# Wrong version is rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("open_store", ["for_project", "read_only", "for_root", "for_root_readonly"])
def test_wrong_version_rejected_all_open_paths(tmp_path, open_store):
    project_id, uow_factory, root = _provision(tmp_path)
    _set_store_meta(root, STORE_SCHEMA_FAMILY, 99)
    with pytest.raises(CardreError) as excinfo:
        if open_store == "for_project":
            uow_factory.for_project(project_id)
        elif open_store == "read_only":
            uow_factory.read_only(project_id)
        elif open_store == "for_root":
            uow_factory.for_root(root)
        else:
            uow_factory.for_root_readonly(root)
    _assert_incompatible(excinfo, root)
