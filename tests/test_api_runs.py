"""Tests for run endpoints."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_run(store):
    """Create a project, plan, plan version, and run."""
    from cardre.services.project_resolver import ProjectResolver
    from cardre.config import CardreConfig

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


def _make_store(project_root: Path):
    """Create a fresh store ready for seeding."""
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root)
    store.initialize()
    return store


def _write_input_csv(project_root: Path) -> Path:
    """Write a tiny CSV input for import_dataset."""
    input_path = project_root / "input.csv"
    input_path.write_text(
        "credit_amount,age_years,credit_risk_class\n"
        "1000,35,good\n"
        "2500,42,bad\n",
        encoding="utf-8",
    )
    return input_path


def _seed_plan_version(store, input_path: Path):
    """Seed a committed plan with import→profile→export steps.

    Returns (project_id, plan_version_id, step_ids).
    Also registers the project in the registry for X-Project-Id resolution.
    """
    from cardre.services.project_resolver import ProjectResolver
    from cardre.config import CardreConfig

    now = utc_now_iso()
    project_id = str(uuid.uuid4())
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

    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    resolver.register_project(project_id, store.root)

    step_ids = ["step-import", "step-profile", "step-export"]
    node_types = [
        "cardre.import_dataset",
        "cardre.profile_dataset",
        "cardre.technical_manifest_export",
    ]
    params_list = [
        json.dumps({"source_path": str(input_path)}),
        json.dumps({}),
        json.dumps({}),
    ]

    for sid, ntype, params, pos in zip(step_ids, node_types, params_list, [0, 1, 2]):
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, pv_id, ntype, "1", "transform",
             params, f"hash-{sid}", "", pos, sid),
        )

    # Edges: import -> profile -> export
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, "step-import", "step-profile", 0),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, ?)",
        (pv_id, "step-profile", "step-export", 0),
    )

    return project_id, pv_id, step_ids


class TestRuns:
    def test_create_run(self, api_client, project_with_run):
        project_id, _, pv_id, _, _, root = project_with_run
        resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
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
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert len(data["runs"]) >= 1

    def test_get_run(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "succeeded"

    def test_get_run_wrong_project(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/runs/{run_id}",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"

    def test_get_run_not_found(self, api_client, project_with_run):
        project_id, _, _, _, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/nonexistent",
            headers={"X-Project-Id": project_id},
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
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_run_steps_wrong_project(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/runs/{run_id}/steps",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"

    def test_list_run_evidence(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_list_run_evidence_wrong_project(self, api_client, project_with_run):
        project_id, _, _, run_id, store, root = project_with_run
        resp = api_client.get(
            f"/projects/{uuid.uuid4()}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"

    def test_real_run_via_api(self, api_client, tmp_path):
        """Exercise a real plan execution through the public API and verify persistence side-effects."""
        tmp = tmp_path / "api-real-run.cardre"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id, step_ids = _seed_plan_version(store, input_path)
        store.close()

        # POST /projects/{project_id}/runs — create and execute synchronously
        resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["plan_version_id"] == pv_id
        assert data["status"] == "succeeded"
        run_id = data["run_id"]
        assert str(uuid.UUID(run_id)) == run_id

        # GET /projects/{project_id}/runs/{run_id}/steps — verify run steps
        resp2 = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/steps",
            headers={"X-Project-Id": project_id},
        )
        assert resp2.status_code == 200
        steps = resp2.json()
        assert isinstance(steps, list)
        assert len(steps) == 3
        api_step_ids = [s["step_id"] for s in steps]
        assert api_step_ids == step_ids
        for s in steps:
            assert s["status"] == "succeeded"

        # Store-level assertions for evidence/artifacts/lineage
        edges = store.execute(
            "SELECT COUNT(*) as cnt FROM evidence_edges WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert edges["cnt"] == 2

        artifacts = store.execute(
            "SELECT COUNT(*) as cnt FROM evidence_artifacts "
            "WHERE evidence_edge_id IN (SELECT evidence_edge_id FROM evidence_edges WHERE run_id = ?)",
            (run_id,),
        ).fetchone()
        assert artifacts["cnt"] == 2

        lineage = store.execute(
            "SELECT COUNT(*) as cnt FROM artifact_lineage WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert lineage["cnt"] == 5
