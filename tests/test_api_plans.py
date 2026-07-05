"""Tests for plan and plan-version endpoints."""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_plan(store):
    """Create a project with a plan and return (project_id, plan_id, pv_id, store, root)."""
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )
    return project_id, plan_id, pv_id, store, store.root


class TestPlans:
    PLAN_FIELDS = {"plan_id", "project_id", "name", "created_at"}
    PLAN_VERSION_FIELDS = {
        "plan_version_id",
        "plan_id",
        "version_number",
        "is_committed",
        "created_at",
        "description",
    }

    def test_list_plans(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plans",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data
        assert len(data["plans"]) >= 1

    def test_list_plans_response_shape(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plans",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["plans"], list)
        assert data["plans"]
        assert set(data["plans"][0].keys()) == self.PLAN_FIELDS

    def test_get_plan_response_shape(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plans/{plan_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == self.PLAN_FIELDS
        assert data["project_id"] == project_id

    def test_create_plan_response_shape(self, raw_project_path, api_client, project_with_plan):
        project_id, _, _, store, root = project_with_plan
        resp = api_client.post(
            f"/projects/{project_id}/plans",
            headers={"X-Project-Path": str(root)},
            json={"name": "New Plan"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert set(data.keys()) == self.PLAN_FIELDS
        assert data["name"] == "New Plan"

    def test_get_plan(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plans/{plan_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_id"] == plan_id

    def test_get_plan_wrong_project(self, raw_project_path, api_client, project_with_plan):
        _, plan_id, _, _, root = project_with_plan
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/plans/{plan_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PLAN_NOT_FOUND"

    def test_get_plan_not_found(self, raw_project_path, api_client, project_with_plan):
        project_id, _, _, _, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plans/nonexistent",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404

    def test_create_plan(self, raw_project_path, api_client, project_with_plan):
        project_id, _, _, store, root = project_with_plan
        resp = api_client.post(
            f"/projects/{project_id}/plans",
            headers={"X-Project-Path": str(root)},
            json={"name": "New Plan"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "New Plan"

    def test_list_plan_versions(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plans/{plan_id}/versions",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert len(data["versions"]) >= 1

    def test_list_plan_versions_response_shape(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plans/{plan_id}/versions",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["versions"], list)
        assert data["versions"]
        assert set(data["versions"][0].keys()) == self.PLAN_VERSION_FIELDS

    def test_get_plan_version(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plan-versions/{pv_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_version_id"] == pv_id

    def test_get_plan_version_response_shape(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.get(
            f"/projects/{project_id}/plan-versions/{pv_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == self.PLAN_VERSION_FIELDS
        assert data["is_committed"] is True

    def test_get_plan_version_wrong_project(self, raw_project_path, api_client, project_with_plan):
        _, _, pv_id, _, root = project_with_plan
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/plan-versions/{pv_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PLAN_VERSION_NOT_FOUND"

    def test_commit_immutable_plan_version(self, raw_project_path, api_client, project_with_plan):
        """Committing an already-committed version returns 409."""
        project_id, plan_id, pv_id, store, root = project_with_plan
        resp = api_client.post(
            f"/projects/{project_id}/plan-versions/{pv_id}/commit",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["detail"]["code"] == "PLAN_VERSION_IMMUTABLE"

    def test_commit_plan_version_response_shape(self, raw_project_path, api_client, project_with_plan):
        project_id, plan_id, pv_id, store, root = project_with_plan
        draft_pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
            "VALUES (?, ?, 2, 0, ?, '')",
            (draft_pv_id, plan_id, utc_now_iso()),
        )

        resp = api_client.post(
            f"/projects/{project_id}/plan-versions/{draft_pv_id}/commit",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == self.PLAN_VERSION_FIELDS
        assert data["plan_version_id"] == draft_pv_id
        assert data["is_committed"] is True

    def test_update_draft_plan_version(self, raw_project_path, api_client, project_with_plan):
        """PATCH description on a draft version."""
        project_id, plan_id, _, store, root = project_with_plan

        # Create a non-committed (draft) version
        draft_pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
            "VALUES (?, ?, 2, 0, ?, '')",
            (draft_pv_id, plan_id, utc_now_iso()),
        )

        resp = api_client.patch(
            f"/projects/{project_id}/plan-versions/{draft_pv_id}",
            headers={"X-Project-Path": str(root)},
            json={"description": "Updated description"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated description"

    def test_patch_immutable_plan_version(self, raw_project_path, api_client, project_with_plan):
        """PATCH on committed version returns 409."""
        project_id, _, pv_id, _, root = project_with_plan
        resp = api_client.patch(
            f"/projects/{project_id}/plan-versions/{pv_id}",
            headers={"X-Project-Path": str(root)},
            json={"description": "Should fail"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["detail"]["code"] == "PLAN_VERSION_IMMUTABLE"
