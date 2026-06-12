"""Sidecar API integration tests using FastAPI TestClient."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardre.store import ProjectStore
from sidecar.main import app
from sidecar.models import ProjectResponse, RunResponse
from sidecar.routes.projects import _load_registry, _save_registry

# Reset registry for fresh state per test
pytest_plugins = []


@pytest.fixture(autouse=True)
def _reset_registry():
    reg_path = Path.home() / ".cardre" / "projects.json"
    if reg_path.exists():
        reg_path.unlink()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_german_credit(tmp_dir):
    p = tmp_dir / "german.data"
    lines = [
        "A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1",
        "A12 24 A32 A43 5951 A61 A73 2 A92 A101 4 A121 22 A142 A152 2 A173 1 A191 A201 2",
    ]
    p.write_text("\n".join(lines))
    return p


# ======================================================================
# Health
# ======================================================================

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["cardre_version"] == "0.1.0"


# ======================================================================
# Projects
# ======================================================================

class TestProjects:
    def test_create_project(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        resp = client.post("/projects", json={"path": str(proj_path), "name": "Test Project"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Project"
        assert (proj_path / "cardre.sqlite").exists()
        for sub in ("datasets", "artifacts", "exports", "logs"):
            assert (proj_path / sub).is_dir()

    def test_create_project_twice(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        resp1 = client.post("/projects", json={"path": str(proj_path), "name": "First"})
        assert resp1.status_code == 201
        resp2 = client.post("/projects", json={"path": str(proj_path), "name": "Second"})
        assert resp2.status_code == 409  # dir already exists

    def test_get_project(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        create_resp = client.post("/projects", json={"path": str(proj_path), "name": "My Project"})
        pid = create_resp.json()["project_id"]

        resp = client.get(f"/projects/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Project"
        assert data["path"] == str(proj_path.resolve())

    def test_get_project_not_found(self, client):
        resp = client.get("/projects/nonexistent-id")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PROJECT_NOT_FOUND"

    def test_project_has_proof_pathway_plan(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        create_resp = client.post("/projects", json={"path": str(proj_path), "name": "Test"})
        pid = create_resp.json()["project_id"]

        detail = client.get(f"/projects/{pid}").json()
        assert detail["plan_count"] >= 1


# ======================================================================
# Dataset Import
# ======================================================================

class TestDatasetImport:
    def test_import_german_credit_file(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        resp = client.post("/datasets/import", json={
            "project_id": proj["project_id"],
            "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["artifact_type"] == "dataset"
        assert data["role"] == "input"
        assert data["media_type"] == "application/vnd.apache.parquet"

    def test_import_missing_file(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        resp = client.post("/datasets/import", json={
            "project_id": proj["project_id"],
            "source_path": str(tmp_dir / "nonexistent.data"),
            "dataset_id": "uci-statlog-german-credit",
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "FILE_NOT_FOUND"


# ======================================================================
# Plans
# ======================================================================

class TestPlans:
    def test_get_proof_pathway_plan(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        proj_detail = client.get(f"/projects/{proj['project_id']}").json()

        from cardre.store import ProjectStore
        store = ProjectStore(proj_path)
        plans = store._connect().execute(
            "SELECT plan_id FROM plans WHERE project_id = ?", (proj["project_id"],)
        ).fetchall()
        plan_id = plans[0]["plan_id"]

        resp = client.get(f"/plans/{plan_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Proof Pathway"
        assert len(data["steps"]) == 6

    def test_plan_has_step_statuses(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        plan_id = store._connect().execute(
            "SELECT plan_id FROM plans WHERE project_id = ?", (proj["project_id"],)
        ).fetchone()["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        client.post("/runs", json={
            "project_id": proj["project_id"],
            "plan_version_id": latest_pv_id,
        })

        resp = client.get(f"/plans/{plan_id}")
        assert resp.status_code == 200
        assert resp.json()["steps"][0]["status"] == "succeeded"


# ======================================================================
# Runs
# ======================================================================

class TestRuns:
    def test_run_proof_pathway(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        plan_id = store._connect().execute(
            "SELECT plan_id FROM plans WHERE project_id = ?", (proj["project_id"],)
        ).fetchone()["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        resp = client.post("/runs", json={
            "project_id": proj["project_id"],
            "plan_version_id": latest_pv_id,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "succeeded"
        assert data["step_count"] > 0

    def test_get_run(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        plan_id = store._connect().execute(
            "SELECT plan_id FROM plans WHERE project_id = ?", (proj["project_id"],)
        ).fetchone()["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)
        run_resp = client.post("/runs", json={
            "project_id": proj["project_id"], "plan_version_id": latest_pv_id,
        })
        run_id = run_resp.json()["run_id"]

        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"

    def test_get_run_steps(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        plan_id = store._connect().execute(
            "SELECT plan_id FROM plans WHERE project_id = ?", (proj["project_id"],)
        ).fetchone()["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)
        run_resp = client.post("/runs", json={
            "project_id": proj["project_id"], "plan_version_id": latest_pv_id,
        })
        run_id = run_resp.json()["run_id"]

        resp = client.get(f"/runs/{run_id}/steps")
        assert resp.status_code == 200
        steps = resp.json()["steps"]
        assert len(steps) > 0
        for step in steps:
            assert step["status"] in ("succeeded", "failed")


# ======================================================================
# Artifacts
# ======================================================================

class TestArtifacts:
    def test_get_artifact(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        import_resp = client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp = client.get(f"/artifacts/{artifact_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_type"] == "dataset"

    def test_get_artifact_not_found(self, client):
        resp = client.get("/artifacts/nonexistent-id")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"


# ======================================================================
# Full round-trip
# ======================================================================

class TestFullRoundTrip:
    def test_create_import_run_view(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "roundtrip.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Roundtrip"}).json()
        pid = proj["project_id"]

        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        assert import_resp.status_code == 201

        store = ProjectStore(proj_path)
        plan_id = store._connect().execute(
            "SELECT plan_id FROM plans WHERE project_id = ?", (pid,)
        ).fetchone()["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        run_resp = client.post("/runs", json={
            "project_id": pid, "plan_version_id": latest_pv_id,
        })
        assert run_resp.status_code == 201
        run_id = run_resp.json()["run_id"]

        steps_resp = client.get(f"/runs/{run_id}/steps")
        assert steps_resp.status_code == 200
        steps = steps_resp.json()["steps"]
        assert all(s["status"] == "succeeded" for s in steps)

        plan_resp = client.get(f"/plans/{plan_id}")
        assert plan_resp.status_code == 200
        assert all(s["is_stale"] is False for s in plan_resp.json()["steps"])
