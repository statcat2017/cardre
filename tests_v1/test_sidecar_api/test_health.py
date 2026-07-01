from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["cardre_version"] == "0.1.0"
