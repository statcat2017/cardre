"""Tests for the health endpoint."""

from __future__ import annotations

import pytest


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient

    from cardre.api.app import create_app
    from cardre.bootstrap.container import build_container
    from cardre.bootstrap.settings import Settings

    return TestClient(create_app(build_container(Settings())))


class TestHealth:
    def test_health_returns_ok(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_no_auth_required(self, api_client):
        """Health endpoint does not require any headers."""
        resp = api_client.get("/health")
        assert resp.status_code == 200
