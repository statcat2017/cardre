"""Tests for evidence endpoints (staleness, keyed by step)."""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_evidence_step(store):
    """Create project with plan, plan version, steps, and evidence edges."""
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
    # Two steps: parent and child
    parent_step_id = "parent-step"
    child_step_id = "child-step"
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, 'parent_node', '1', 'fit', '{}', 'abc', '', 0, ?)",
        (parent_step_id, pv_id, parent_step_id),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, 'child_node', '1', 'fit', '{}', 'def', '', 1, ?)",
        (child_step_id, pv_id, child_step_id),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, 0)",
        (pv_id, parent_step_id, child_step_id),
    )
    # Insert a run with evidence
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?)",
        (run_id, pv_id, now, now),
    )
    rs_child = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
        (rs_child, run_id, child_step_id, pv_id, now, now),
    )
    # Add parent run step
    rs_parent = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
        (rs_parent, run_id, parent_step_id, pv_id, now, now),
    )
    # Evidence edge
    ee_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO evidence_edges "
        "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
        " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, stale_reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
        (ee_id, run_id, rs_child, pv_id, child_step_id, parent_step_id,
         run_id, rs_parent, "exact", "parent", now),
    )

    return project_id, plan_id, pv_id, child_step_id, store, store.root


class TestEvidence:
    def test_get_step_evidence_staleness(self, api_client, project_with_evidence_step):
        project_id, _, pv_id, child_step_id, store, root = project_with_evidence_step
        resp = api_client.get(
            f"/projects/{project_id}/steps/{child_step_id}/evidence",
            params={"plan_version_id": pv_id},
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["step_id"] == child_step_id
        assert "status" in data
        assert "upstream_changes" in data
        assert "missing_evidence" in data

    def test_get_step_evidence_missing_plan_version(self, api_client, project_with_evidence_step):
        project_id, _, _, child_step_id, _, root = project_with_evidence_step
        resp = api_client.get(
            f"/projects/{project_id}/steps/{child_step_id}/evidence",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "MISSING_PARAMETER" in data["detail"]["code"]

    def test_get_step_evidence_not_found(self, api_client, project_with_evidence_step):
        project_id, _, pv_id, _, _, root = project_with_evidence_step
        resp = api_client.get(
            f"/projects/{project_id}/steps/nonexistent/evidence",
            params={"plan_version_id": pv_id},
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "STEP_NOT_FOUND"

    def test_get_step_evidence_edges(self, api_client, project_with_evidence_step):
        project_id, _, pv_id, child_step_id, store, root = project_with_evidence_step
        resp = api_client.get(
            f"/projects/{project_id}/steps/{child_step_id}/evidence/edges",
            params={"plan_version_id": pv_id},
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
