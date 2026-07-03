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

        get_resp = api_client.get(
            f"/projects/{project_id}",
            headers={"X-Project-Id": project_id},
        )

        assert get_resp.status_code == 200, get_resp.text
        body = get_resp.json()
        assert body["project_id"] == project_id
        assert body["name"] == "Registry Project"

    def test_missing_project_id_returns_structured_error(self, api_client):
        resp = api_client.get("/projects/some-id")

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "MISSING_PROJECT_ID"

    def test_raw_project_path_is_rejected_when_dev_flag_is_off(self, api_client, tmp_path, monkeypatch):
        monkeypatch.delenv("CARDRE_ALLOW_RAW_PROJECT_PATH", raising=False)
        project_dir = tmp_path / "raw-project.cardre"

        create_resp = api_client.post(
            "/projects",
            json={"name": "Raw Project", "path": str(project_dir)},
        )
        assert create_resp.status_code == 201, create_resp.text
        project_id = create_resp.json()["project_id"]

        resp = api_client.get(
            f"/projects/{project_id}",
            headers={"X-Project-Path": str(project_dir)},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "RAW_PROJECT_PATH_DISABLED"
