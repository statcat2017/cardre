"""Shared pytest fixtures for the cardre test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cardre.store import ProjectStore


@pytest.fixture
def store():
    """Create an isolated ProjectStore in a temp directory."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    s = ProjectStore(tmp / "test.cardre")
    s.initialize()
    return s


@pytest.fixture
def client():
    """FastAPI TestClient bound to the sidecar app."""
    from fastapi.testclient import TestClient
    from sidecar.main import app
    return TestClient(app)


@pytest.fixture
def bare_app():
    """Raw FastAPI app instance (for dependency overrides, etc.)."""
    from sidecar.main import app
    return app


@pytest.fixture
def _isolated_registry(tmp_path, monkeypatch):
    """Isolate the project registry to a temp path.

    Apply with ``pytest.mark.usefixtures("_isolated_registry")`` or
    ``pytestmark = pytest.mark.usefixtures("_isolated_registry")``.
    """
    registry = tmp_path / "registry" / "projects.json"
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(registry))
