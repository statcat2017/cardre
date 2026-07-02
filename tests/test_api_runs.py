"""Tests for run endpoints."""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_run(store):
    """Create a project, plan, plan version, and run."""
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
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (run_id, pv_id, now, now),
    )
    return project_id, plan_id, pv_id, run_id, store, store.root


class TestRuns:
    def test_create_run(self, api_client, project_with_run):
        project_id, _, pv_id, _, _, root = project_with_run
        resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Path": str(root)},
            json={"plan_version_id": pv_id, "sync": True, "force": False},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["plan_version_id"] == pv_id
        assert data["status"] == "succeeded"

    def test_list_runs(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert len(data["runs"]) >= 1

    def test_get_run(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "succeeded"

    def test_get_run_wrong_project(self, api_client, project_with_run):
        _, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/runs/{run_id}",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"

    def test_get_run_not_found(self, api_client, project_with_run):
        project_id, _, _, _, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/nonexistent",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data

    def test_list_run_steps(self, api_client, project_with_run):
        project_id, _, pv_id, run_id, store, root = project_with_run
        # Insert a run step
        step_id = "test-step"
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'test', '1', 'fit', '{}', 'abc', '', 0, ?)",
            (step_id, pv_id, step_id),
        )
        now = utc_now_iso()
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            ("rs-1", run_id, step_id, pv_id, now, now),
        )

        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/steps",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_run_steps_wrong_project(self, api_client, project_with_run):
        _, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/runs/{run_id}/steps",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"

    def test_list_run_evidence(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_run_evidence_wrong_project(self, api_client, project_with_run):
        _, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/runs/{run_id}/evidence",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"
