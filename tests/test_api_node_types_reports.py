"""Tests for node-types, reports, and artifacts API routes."""
from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso


@pytest.fixture
def project_with_steps(store):
    project_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, 'cardre.noop', '1', 'transform', '{}', 'h', '', 0, ?)",
        ("s1", pv_id, "s1"),
    )
    return project_id, pv_id, store, store.root


class TestNodeTypesRoutes:
    @pytest.fixture(autouse=True)
    def _enable_raw_path(self, raw_project_path):
        pass

    def test_list_node_types_with_data(self, api_client, project_with_steps):
        project_id, _, _, root = project_with_steps
        resp = api_client.get(
            f"/projects/{project_id}/node-types",
            headers={"X-Project-Path": str(root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "node_types" in data
        assert any(nt["node_type"] == "cardre.noop" for nt in data["node_types"])

    def test_list_node_types_empty_returns_defaults(self, api_client, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        resp = api_client.get(
            f"/projects/{project_id}/node-types",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["node_types"]) > 0


class TestReportsRoutes:
    @pytest.fixture(autouse=True)
    def _enable_raw_path(self, raw_project_path):
        pass

    def test_list_reports_empty(self, api_client, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        resp = api_client.get(
            f"/projects/{project_id}/reports",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reports" in data
        assert isinstance(data["reports"], list)

    def test_list_run_reports_empty(self, api_client, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        resp = api_client.get(
            f"/projects/{project_id}/runs/nonexistent/reports",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"

    def test_list_run_reports_existing_run_no_reports(self, api_client, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', ?, ?, ?)",
            (run_id, pv_id, now, now, now),
        )
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/reports",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reports" in data
        assert isinstance(data["reports"], list)
        assert len(data["reports"]) == 0

    def test_list_reports_with_manifest(self, api_client, store):
        import json
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', ?, ?, ?)",
            (run_id, pv_id, now, now, now),
        )
        manifest_dir = store.root / "exports" / f"manifest-{run_id}"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(json.dumps({"run_id": run_id}))

        resp = api_client.get(
            f"/projects/{project_id}/reports",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert any(r["run_id"] == run_id for r in data["reports"])

        resp2 = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/reports",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["reports"]) >= 1
        assert data2["reports"][0]["run_id"] == run_id


class TestArtifactsRoute:
    @pytest.fixture(autouse=True)
    def _enable_raw_path(self, raw_project_path):
        pass

    def _seed_project_with_artifact(self, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'cardre.noop', '1', 'transform', '{}', 'h', '', 0, ?)",
            ("step-art", pv_id, "step-art"),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', ?, ?, ?)",
            (run_id, pv_id, now, now, now),
        )
        rs_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
            " started_at, finished_at, execution_fingerprint_json) "
            "VALUES (?, ?, 'step-art', ?, 'succeeded', ?, ?, '{}')",
            (rs_id, run_id, pv_id, now, now),
        )
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, "
            "media_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("art-proj-1", "test", "test", "/tmp/test.json", "ph", "lh", "application/json", now),
        )
        store.execute(
            "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, step_id, "
            " artifact_id, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, rs_id, pv_id, "step-art", "art-proj-1", "output", now),
        )
        return project_id

    def test_get_artifact_not_found(self, api_client, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        resp = api_client.get(
            f"/projects/{project_id}/artifacts/nonexistent",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"

    def test_get_artifact_success(self, api_client, store):
        project_id = self._seed_project_with_artifact(store)
        resp = api_client.get(
            f"/projects/{project_id}/artifacts/art-proj-1",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == "art-proj-1"
        assert data["artifact_type"] == "test"
        assert data["role"] == "test"
        assert data["path"] == "/tmp/test.json"
        assert data["physical_hash"] == "ph"
        assert data["logical_hash"] == "lh"
        assert data["media_type"] == "application/json"
        assert "created_at" in data

    def test_get_artifact_wrong_project_returns_404(self, api_client, store):
        project_id = self._seed_project_with_artifact(store)
        other_project = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (other_project, "Other", now, "0.2.0"),
        )
        resp = api_client.get(
            f"/projects/{other_project}/artifacts/art-proj-1",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"


class TestExportsRoute:
    @pytest.fixture(autouse=True)
    def _enable_raw_path(self, raw_project_path):
        pass

    def test_list_exports_empty(self, api_client, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        resp = api_client.get(
            f"/projects/{project_id}/exports",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "exports" in data
        assert isinstance(data["exports"], list)

    def test_list_exports_with_data(self, api_client, store):
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        export_dir = store.root / "exports" / "export-testrun"
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "scoring.py").write_text("# test export")

        resp = api_client.get(
            f"/projects/{project_id}/exports",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["exports"]) >= 1
        assert data["exports"][0]["export_id"] == "export-testrun"

        resp2 = api_client.get(
            f"/projects/{project_id}/exports?run_id=testrun",
            headers={"X-Project-Path": str(store.root)},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["exports"]) >= 1
