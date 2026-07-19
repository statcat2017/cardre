"""Tests for project endpoints."""

from __future__ import annotations


class TestProjects:
    PROJECT_FIELDS = {"project_id", "name", "created_at", "cardre_version"}

    def test_list_projects(self, api_client, registered_project):
        project_id, store, root = registered_project
        resp = api_client.get("/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert "projects" in data
        assert len(data["projects"]) >= 1

    def test_list_projects_response_shape(self, api_client, registered_project):
        project_id, store, root = registered_project
        resp = api_client.get("/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"projects", "unavailable_projects"}
        assert isinstance(data["projects"], list)
        assert data["projects"]
        assert set(data["projects"][0].keys()) == self.PROJECT_FIELDS

    def test_get_project(self, api_client, registered_project):
        project_id, store, root = registered_project
        resp = api_client.get(f"/projects/{project_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == project_id
        assert data["name"] == "Test Project"

    def test_get_project_response_shape(self, api_client, registered_project):
        project_id, store, root = registered_project
        resp = api_client.get(f"/projects/{project_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == self.PROJECT_FIELDS
        assert data["project_id"] == project_id

    def test_get_project_not_found(self, api_client, registered_project):
        _, store, root = registered_project
        resp = api_client.get("/projects/nonexistent-id")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data
        assert data["detail"]["code"] == "PROJECT_NOT_FOUND"

    def test_get_project_missing_header(self, api_client):
        # /projects/{id} now resolves via registry, no header needed.
        # A missing project returns 404, not 400 MISSING_PROJECT_ID.
        resp = api_client.get("/projects/nonexistent-id")
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "PROJECT_NOT_FOUND"

    def test_create_project_bootstraps_fresh_store(self, api_client, tmp_path):
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

    def test_create_project_response_shape(self, api_client, tmp_path):
        from cardre.store.db import ProjectStore

        project_dir = tmp_path / "new-project-shape.cardre"
        resp = api_client.post(
            "/projects",
            json={"name": "My Project", "path": str(project_dir)},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert set(body.keys()) == self.PROJECT_FIELDS
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
        resp2 = api_client.get(f"/projects/{pid}")
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

    def test_cardre_dirs_are_gitignored(self):
        import subprocess
        result = subprocess.run(
            ["git", "check-ignore", "some/path.cardre/cardre.sqlite"],
            capture_output=True, text=True, cwd=subprocess.run(
                ["git", "rev-parse", "--show-toplevel"], capture_output=True,
                text=True, check=True,
            ).stdout.strip(),
        )
        assert result.returncode == 0, (
            f"*.cardre/ dirs are not gitignored: {result.stderr}"
        )
