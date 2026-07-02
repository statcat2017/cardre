"""Tests for project endpoints."""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_store(store):
    """Create a project in the store and return (project_id, store, root)."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )
    return project_id, store, store.root


class TestProjects:
    def test_list_projects(self, api_client, project_with_store):
        project_id, store, root = project_with_store
        resp = api_client.get("/projects", headers={"X-Project-Path": str(root)})
        assert resp.status_code == 200
        data = resp.json()
        assert "projects" in data
        assert len(data["projects"]) >= 1

    def test_get_project(self, api_client, project_with_store):
        project_id, store, root = project_with_store
        resp = api_client.get(
            f"/projects/{project_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == project_id
        assert data["name"] == "Test Project"

    def test_get_project_not_found(self, api_client, project_with_store):
        _, store, root = project_with_store
        resp = api_client.get(
            "/projects/nonexistent-id",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert data["detail"]["code"] == "PROJECT_NOT_FOUND"

    def test_get_project_missing_header(self, api_client):
        resp = api_client.get("/projects/some-id")
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["code"] == "MISSING_PROJECT_PATH"

    def test_create_project_bootstraps_fresh_store(self, api_client, tmp_path):
        from cardre.store.db import ProjectStore
        project_dir = tmp_path / "new-project.cardre"
        resp = api_client.post(
            "/projects",
            json={"name": "My Project", "path": str(project_dir)},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "My Project"
        assert body["project_id"]
        assert (project_dir / "cardre.sqlite").exists()
        assert (project_dir / "datasets").is_dir()
        s = ProjectStore(project_dir)
        s.open()
        family = s.execute("SELECT value FROM store_meta WHERE key='schema_family'").fetchone()
        assert family["value"] == "cardre-v2"
        s.close()

    def test_create_project_rejects_existing_store(self, api_client, tmp_path):
        from cardre.store.db import ProjectStore
        p = tmp_path / "exists.cardre"
        ProjectStore(p).initialize()
        resp = api_client.post("/projects", json={"name": "X", "path": str(p)})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "STORE_ALREADY_EXISTS"

    def test_get_project_after_create_via_api(self, api_client, tmp_path):
        project_dir = tmp_path / "roundtrip.cardre"
        resp = api_client.post("/projects", json={"name": "RT", "path": str(project_dir)})
        assert resp.status_code == 201
        pid = resp.json()["project_id"]
        resp2 = api_client.get(
            f"/projects/{pid}",
            headers={"X-Project-Path": str(project_dir)},
        )
        assert resp2.status_code == 200
        assert resp2.json()["project_id"] == pid

    def test_create_project_rejects_relative_path(self, api_client, tmp_path):
        resp = api_client.post("/projects", json={"name": "X", "path": "relative/path.cardre"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_PROJECT_PATH"

    def test_create_project_rejects_parent_traversal(self, api_client, tmp_path):
        traversal = str(tmp_path / "legit.cardre" / ".." / "escape.cardre")
        resp = api_client.post("/projects", json={"name": "X", "path": traversal})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_PROJECT_PATH"
