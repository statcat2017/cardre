"""Characterization tests that pin the exact JSON shape of run/step/evidence responses.

These tests assert the full field set and values returned by each endpoint,
serving as a safety net for the mapper extraction refactor in Slice 1.
"""

from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso

# ---------------------------------------------------------------------------
# Local fixture — mirrors the one in test_api_runs.py but self-contained so
# this test file can be run independently.
# ---------------------------------------------------------------------------


@pytest.fixture
def project_with_run(store):
    """Create a project, plan, plan version, and run (no steps / evidence)."""
    from cardre.config import CardreConfig
    from cardre.services.project_resolver import ProjectResolver

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
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )
    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    resolver.register_project(project_id, store.root)
    return project_id, plan_id, pv_id, run_id, store, store.root


# ---------------------------------------------------------------------------
# RunResponse shape
# ---------------------------------------------------------------------------


class TestRunResponseShape:
    """Pin the exact field set and values of RunResponse."""

    def test_run_response_from_get_run(self, api_client, project_with_run):
        project_id, _, _, run_id, _, _ = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()

        expected_fields = {
            "run_id",
            "plan_version_id",
            "status",
            "started_at",
            "finished_at",
            "step_count",
            "branch_id",
            "executed_step_ids",
            "diagnostics",
            "latest_error",
            "heartbeat_at",
            "is_stale",
        }
        assert set(data.keys()) == expected_fields, f"Unexpected fields: {set(data.keys()) ^ expected_fields}"

        assert data["run_id"] == run_id
        assert data["status"] == "succeeded"
        assert data["step_count"] == 0
        assert data["branch_id"] is None
        assert data["executed_step_ids"] == []
        assert data["diagnostics"] == []
        assert data["latest_error"] is None
        assert data["heartbeat_at"] is None
        assert data["is_stale"] is False

    def test_run_response_from_create_run(self, api_client, project_with_run):
        project_id, _, pv_id, _, _, _ = project_with_run
        resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": False},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        expected_fields = {
            "run_id",
            "plan_version_id",
            "status",
            "started_at",
            "finished_at",
            "step_count",
            "branch_id",
            "executed_step_ids",
            "diagnostics",
            "latest_error",
            "heartbeat_at",
            "is_stale",
        }
        assert set(data.keys()) == expected_fields, f"Unexpected fields: {set(data.keys()) ^ expected_fields}"

        assert data["plan_version_id"] == pv_id
        assert data["status"] == "succeeded"
        assert data["step_count"] == 0
        assert data["executed_step_ids"] == []
        assert data["diagnostics"] == []


# ---------------------------------------------------------------------------
# RunStepResponse shape
# ---------------------------------------------------------------------------


class TestRunStepResponseShape:
    """Pin the exact field set and values of RunStepResponse."""

    def test_run_step_response_shape(self, api_client, project_with_run):
        project_id, _, pv_id, run_id, store, _ = project_with_run

        # Insert a plan step (required FK for run_steps.step_id)
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'test', '1', 'fit', '{}', 'abc', '', 0, ?)",
            ("test-step", pv_id, "test-step"),
        )

        now = utc_now_iso()
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            ("rs-1", run_id, "test-step", pv_id, now, now),
        )

        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/steps",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

        step = data[0]
        expected_fields = {
            "run_step_id",
            "run_id",
            "step_id",
            "plan_version_id",
            "status",
            "started_at",
            "finished_at",
            "execution_fingerprint",
            "warnings",
            "errors",
        }
        assert set(step.keys()) == expected_fields, f"Unexpected fields: {set(step.keys()) ^ expected_fields}"

        assert step["run_step_id"] == "rs-1"
        assert step["run_id"] == run_id
        assert step["step_id"] == "test-step"
        assert step["plan_version_id"] == pv_id
        assert step["status"] == "succeeded"
        assert step["finished_at"] == now
        assert step["execution_fingerprint"] == {}
        assert step["warnings"] == []
        assert step["errors"] == []


# ---------------------------------------------------------------------------
# RunEvidenceEdgeResponse shape (including nested artifacts)
# ---------------------------------------------------------------------------


class TestRunEvidenceResponseShape:
    """Pin the exact field set and values of RunEvidenceEdgeResponse."""

    def test_run_evidence_response_shape(self, api_client, project_with_run):
        project_id, _, pv_id, run_id, store, _ = project_with_run

        now = utc_now_iso()

        # Insert a plan step
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'test', '1', 'fit', '{}', 'abc', '', 0, ?)",
            ("step-a", pv_id, "step-a"),
        )

        # Insert a run step
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            (rs_id, run_id, "step-a", pv_id, now, now),
        )

        # Insert an artifact (required FK for evidence_artifacts)
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("art-001", "dataset", "input", "/tmp/art.csv", "abc", "def", "text/csv", now),
        )

        # Insert an evidence edge
        ee_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO evidence_edges "
            "(evidence_edge_id, run_id, run_step_id, plan_version_id, step_id, parent_step_id, "
            " source_run_id, source_run_step_id, policy, source_label, is_reused, is_stale, "
            " stale_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?)",
            (ee_id, run_id, rs_id, pv_id, "step-a", "",
             run_id, rs_id, "exact", "parent", now),
        )

        # Insert an evidence artifact
        ea_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO evidence_artifacts (evidence_artifact_id, evidence_edge_id, artifact_id, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ea_id, ee_id, "art-001", "input", now),
        )

        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

        edge = data[0]
        expected_edge_fields = {
            "evidence_edge_id",
            "run_id",
            "run_step_id",
            "plan_version_id",
            "step_id",
            "parent_step_id",
            "source_run_id",
            "source_run_step_id",
            "policy",
            "source_label",
            "is_reused",
            "is_stale",
            "stale_reason",
            "created_at",
            "artifacts",
        }
        assert set(edge.keys()) == expected_edge_fields, (
            f"Unexpected edge fields: {set(edge.keys()) ^ expected_edge_fields}"
        )

        assert edge["evidence_edge_id"] == ee_id
        assert edge["run_id"] == run_id
        assert edge["run_step_id"] == rs_id
        assert edge["plan_version_id"] == pv_id
        assert edge["step_id"] == "step-a"
        assert edge["is_reused"] is False
        assert edge["is_stale"] is False
        assert edge["stale_reason"] is None
        assert edge["created_at"] == now

        # Nested artifacts
        artifacts = edge["artifacts"]
        assert isinstance(artifacts, list)
        assert len(artifacts) == 1
        art = artifacts[0]

        expected_artifact_fields = {
            "evidence_artifact_id",
            "evidence_edge_id",
            "artifact_id",
            "role",
            "created_at",
        }
        assert set(art.keys()) == expected_artifact_fields, (
            f"Unexpected artifact fields: {set(art.keys()) ^ expected_artifact_fields}"
        )

        assert art["evidence_artifact_id"] == ea_id
        assert art["evidence_edge_id"] == ee_id
        assert art["artifact_id"] == "art-001"
        assert art["role"] == "input"
        # created_at defaults to "" when not explicitly provided
        assert art["created_at"] == "", f"Expected empty created_at default, got {art['created_at']!r}"
