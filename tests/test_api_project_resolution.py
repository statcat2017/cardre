"""Tests for registry-backed project resolution."""

from __future__ import annotations


class TestProjectResolution:
    def test_create_project_registers_project_id(self, api_client, tmp_path):
        project_dir = tmp_path / "registry-project.cardre"

        create_resp = api_client.post(
            "/projects",
            json={"name": "Registry Project", "path": str(project_dir)},
        )
        assert create_resp.status_code == 201, create_resp.text
        project_id = create_resp.json()["project_id"]

        get_resp = api_client.get(f"/projects/{project_id}")

        assert get_resp.status_code == 200, get_resp.text
        body = get_resp.json()
        assert body["project_id"] == project_id
        assert body["name"] == "Registry Project"

    def test_missing_project_id_returns_404(self, api_client):
        """Unknown project ID returns 404 PROJECT_NOT_FOUND via the registry."""
        resp = api_client.get("/projects/nonexistent-id")

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PROJECT_NOT_FOUND"

    def test_raw_project_path_is_rejected_on_scoped_routes(self, api_client, tmp_path, monkeypatch):
        """X-Project-Path is rejected on project-scoped routes (runs, plans, etc)."""
        monkeypatch.delenv("CARDRE_ALLOW_RAW_PROJECT_PATH", raising=False)

        resp = api_client.get(
            "/projects/some-id/runs",
            headers={"X-Project-Path": str(tmp_path)},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "RAW_PROJECT_PATH_DISABLED"
