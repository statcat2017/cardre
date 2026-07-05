from __future__ import annotations

import uuid


class TestDependencies:
    def test_missing_x_project_id_returns_400(self, api_client):
        resp = api_client.get("/projects/some-id/runs")
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["code"] == "MISSING_PROJECT_ID"

    def test_raw_project_path_disabled_by_default(self, api_client, tmp_path):
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/runs",
            headers={"X-Project-Path": str(tmp_path)},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["code"] == "RAW_PROJECT_PATH_DISABLED"

    def test_raw_project_path_not_found(self, raw_project_path, api_client, tmp_path):
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}",
            headers={"X-Project-Path": str(tmp_path / "nonexistent")},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "PROJECT_NOT_FOUND"

    def test_invalid_project_id_resolves_404(self, api_client):
        resp = api_client.get(
            "/projects/nonexistent-id",
            headers={"X-Project-Id": "nonexistent-id"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data

    def test_governance_disabled_on_branch_route(self, api_client, raw_project_path, monkeypatch):
        monkeypatch.setattr("cardre.config.CardreConfig.from_env", lambda: type(
            "MockConfig", (), {
                "governance_enabled": False, "launch_mode": True,
                "stale_heartbeat_seconds": 300, "heartbeat_watchdog_interval_seconds": 75,
                "api_host": "127.0.0.1", "api_port": 8752, "registry_path": "/tmp",
            }
        )())
        project_id = str(uuid.uuid4())
        resp = api_client.get(
            f"/projects/{project_id}/branches",
            headers={"X-Project-Path": "/tmp"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["detail"]["code"] == "GOVERNANCE_DISABLED"

    def test_health_endpoint(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
