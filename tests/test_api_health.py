"""Tests for the health endpoint."""

from __future__ import annotations


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
