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

    def test_create_project(self, api_client, store):
        root = store.root
        resp = api_client.post(
            "/projects",
            headers={"X-Project-Path": str(root)},
            json={"name": "New Project"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "New Project"
        assert "project_id" in data
