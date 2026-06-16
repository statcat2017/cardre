"""Tests for the project registry service."""

import json
from pathlib import Path

import pytest

from cardre.store import ProjectStore
from cardre.services.project_registry import (
    create_project_registry_entry,
    get_store_for_project,
    ProjectNotFoundError,
    validate_project_path,
)


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    registry = tmp_path / "registry" / "projects.json"
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(registry))


def test_create_and_get_project(tmp_path: Path):
    """Create a project registry entry and retrieve its store."""
    proj_path = tmp_path / "test.cardre"
    store = ProjectStore(proj_path)
    store.initialize()
    project_id = store.create_project("Test Project")

    create_project_registry_entry(project_id, proj_path, "Test Project")

    retrieved_store = get_store_for_project(project_id)
    proj = retrieved_store.get_project(project_id)
    assert proj is not None
    assert proj["name"] == "Test Project"


def test_get_store_for_missing_project():
    with pytest.raises(ProjectNotFoundError):
        get_store_for_project("nonexistent-id")


def test_validate_project_path(tmp_path: Path):
    """Valid path should not raise."""
    validate_project_path(tmp_path / "valid.cardre")


def test_validate_project_path_exists(tmp_path: Path):
    """Existing directory that is not a cardre project should raise."""
    path = tmp_path / "other_dir"
    path.mkdir()
    with pytest.raises(ValueError, match="DIR_EXISTS"):
        validate_project_path(path)
