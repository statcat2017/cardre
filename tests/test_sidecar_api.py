"""Sidecar API integration tests using FastAPI TestClient."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardre.audit import StepSpec, json_logical_hash
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

    def test_run_failure_path(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        store = ProjectStore(proj_path)
        plan_id = store._connect().execute(
            "SELECT plan_id FROM plans WHERE project_id = ?", (proj["project_id"],)
        ).fetchone()["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        # Run without importing data — the import step has no source_path
        # and should fail
        resp = client.post("/runs", json={
            "project_id": proj["project_id"],
            "plan_version_id": latest_pv_id,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "failed"

        # Verify only one run record exists for this plan version
        all_runs = store.list_runs(data["plan_version_id"])
        matching = [r for r in all_runs if r["run_id"] == data["run_id"]]
        assert len(matching) == 1, "Expected exactly one run record for the failed run"

        # Verify only one run record exists for this plan version
        all_runs = store.list_runs(data["plan_version_id"])
        matching = [r for r in all_runs if r["run_id"] == data["run_id"]]
        assert len(matching) == 1, "Expected exactly one run record for the failed run"

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

        # After import, the proof pathway should still have 6 steps
        pathway_steps = store.get_plan_version_steps(latest_pv_id)
        assert len(pathway_steps) == 6, f"Expected 6 pathway steps, got {len(pathway_steps)}"

        run_resp = client.post("/runs", json={
            "project_id": pid, "plan_version_id": latest_pv_id,
        })
        assert run_resp.status_code == 201
        run_id = run_resp.json()["run_id"]

        steps_resp = client.get(f"/runs/{run_id}/steps")
        assert steps_resp.status_code == 200
        steps = steps_resp.json()["steps"]
        assert len(steps) == 6, f"Expected 6 run steps, got {len(steps)}"
        assert all(s["status"] == "succeeded" for s in steps)

        plan_resp = client.get(f"/plans/{plan_id}")
        assert plan_resp.status_code == 200
        assert all(s["is_stale"] is False for s in plan_resp.json()["steps"])
        assert len(plan_resp.json()["steps"]) == 6

    def test_import_does_not_overwrite_proof_pathway(self, client, tmp_dir, sample_german_credit):
        """After import, the proof pathway plan must still have 6 steps and
        the __import__ plan must exist separately."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)

        # Verify proof pathway exists before import
        plans_before = store.get_plans_for_project(pid)
        proof_before = [p for p in plans_before if p["name"] == "Proof Pathway"]
        assert len(proof_before) == 1
        proof_plan_id = proof_before[0]["plan_id"]

        # Import via API
        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        # Re-fetch plans after import
        plans_after = store.get_plans_for_project(pid)

        # Proof pathway should still have 6 steps
        proof_after = [p for p in plans_after if p["name"] == "Proof Pathway"]
        assert len(proof_after) == 1
        latest_pv_id = store.get_latest_plan_version_id(proof_after[0]["plan_id"])
        assert latest_pv_id is not None
        steps = store.get_plan_version_steps(latest_pv_id)
        assert len(steps) == 6, f"Proof pathway has {len(steps)} steps, expected 6"

        # __import__ plan should exist as a separate plan
        import_plans = [p for p in plans_after if p["name"] == "__import__"]
        assert len(import_plans) == 1, "Expected __import__ plan to exist after import"
        assert import_plans[0]["plan_id"] != proof_plan_id, "Import plan must be distinct from proof pathway"

    def test_unknown_node_type_produces_failed_run(self, client, tmp_dir, sample_german_credit):
        """A plan step with an unknown node type must produce a failed
        run with structured error evidence, not leave the run stuck as
        running."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plan_id = store.create_plan(pid, "Broken Plan")
        bad_step = StepSpec(
            step_id="bad", node_type="cardre.nonexistent",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        )
        bad_pv_id = store.create_plan_version(plan_id, [bad_step])

        resp = client.post("/runs", json={
            "project_id": pid, "plan_version_id": bad_pv_id,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "failed"

        # Verify run-step records exist with error evidence
        steps_resp = client.get(f"/runs/{data['run_id']}/steps")
        assert steps_resp.status_code == 200
        steps = steps_resp.json()["steps"]
        assert len(steps) > 0
        has_error = any(len(s.get("errors", [])) > 0 for s in steps)
        assert has_error, "Expected at least one step with structured error evidence"


# ======================================================================
# Project Plans Discovery
# ======================================================================

class TestProjectPlans:
    def test_get_project_plans(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        resp = client.get(f"/projects/{pid}/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == pid
        assert len(data["plans"]) >= 2

        names = [p["name"] for p in data["plans"]]
        assert "Scorecard Pathway" in names
        assert "Proof Pathway" in names

    def test_scorecard_is_default(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        resp = client.get(f"/projects/{proj['project_id']}/plans")
        scorecard = [p for p in resp.json()["plans"] if p["name"] == "Scorecard Pathway"]
        assert len(scorecard) == 1
        assert scorecard[0]["is_default"] is True

    def test_hidden_import_excluded(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        resp = client.get(f"/projects/{pid}/plans")
        names = [p["name"] for p in resp.json()["plans"]]
        assert "__import__" not in names

    def test_plans_have_latest_version_id(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        resp = client.get(f"/projects/{proj['project_id']}/plans")
        for plan in resp.json()["plans"]:
            assert plan["latest_version_id"] is not None
            assert len(plan["latest_version_id"]) > 0

    def test_project_not_found(self, client):
        resp = client.get("/projects/nonexistent/plans")
        assert resp.status_code == 404


# ======================================================================
# Manifest Ordering
# ======================================================================

class TestManifestOrdering:
    def test_scorecard_pathway_has_manifest_at_end(self, client, tmp_dir):
        """The technical-manifest-stub step should be at the end of the
        Scorecard Pathway, after cutoff-analysis."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        # Find the Scorecard Pathway plan
        all_plans = store.get_plans_for_project(pid)
        scorecard_plans = [p for p in all_plans if p["name"] == "Scorecard Pathway"]
        assert len(scorecard_plans) == 1
        plan_id = scorecard_plans[0]["plan_id"]

        latest_pv_id = store.get_latest_plan_version_id(plan_id)
        steps = store.get_plan_version_steps(latest_pv_id)

        step_ids = [s.step_id for s in steps]
        assert "technical-manifest-stub" in step_ids
        assert "cutoff-analysis" in step_ids

        manifest_pos = step_ids.index("technical-manifest-stub")
        cutoff_pos = step_ids.index("cutoff-analysis")
        assert manifest_pos > cutoff_pos, (
            f"technical-manifest-stub (pos {manifest_pos}) should be after "
            f"cutoff-analysis (pos {cutoff_pos})"
        )

    def test_manifest_depends_on_cutoff_and_model_steps(self, client, tmp_dir):
        """The manifest step should depend on model, scoring, validation, and cutoff steps."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        all_plans = store.get_plans_for_project(pid)
        scorecard_plans = [p for p in all_plans if p["name"] == "Scorecard Pathway"]
        plan_id = scorecard_plans[0]["plan_id"]

        latest_pv_id = store.get_latest_plan_version_id(plan_id)
        steps = store.get_plan_version_steps(latest_pv_id)

        manifest_step = [s for s in steps if s.step_id == "technical-manifest-stub"][0]
        assert "cutoff-analysis" in manifest_step.parent_step_ids
        assert "validation-metrics" in manifest_step.parent_step_ids
        assert "logistic-regression" in manifest_step.parent_step_ids
        assert "score-scaling" in manifest_step.parent_step_ids


# ======================================================================
# Step Params Update (Phase 3C)
# ======================================================================

class TestStepParamsUpdate:
    def test_update_step_params_creates_new_version(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        orig_pv_id = store.get_latest_plan_version_id(plan_id)

        resp = client.post(f"/plans/{plan_id}/steps/fine-classing/params", json={
            "project_id": pid,
            "base_plan_version_id": orig_pv_id,
            "params": {"max_bins": 25, "min_bin_fraction": 0.03},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_id"] == plan_id
        assert data["new_plan_version_id"] != orig_pv_id
        assert data["changed_step_id"] == "fine-classing"
        assert len(data["stale_step_ids"]) > 0

    def test_update_params_invalid_step(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        orig_pv_id = store.get_latest_plan_version_id(plan_id)

        resp = client.post(f"/plans/{plan_id}/steps/nonexistent-step/params", json={
            "project_id": pid,
            "base_plan_version_id": orig_pv_id,
            "params": {},
        })
        assert resp.status_code == 404

    def test_update_params_rejects_stale_version(self, client, tmp_dir):
        """P1#1: Stale base_plan_version_id must be rejected with 409."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        v1_pv_id = store.get_latest_plan_version_id(plan_id)

        # Update once to create v2
        client.post(f"/plans/{plan_id}/steps/fine-classing/params", json={
            "project_id": pid, "base_plan_version_id": v1_pv_id,
            "params": {"max_bins": 30},
        })

        # Try updating with stale v1 id — should get 409
        resp = client.post(f"/plans/{plan_id}/steps/fine-classing/params", json={
            "project_id": pid, "base_plan_version_id": v1_pv_id,
            "params": {"max_bins": 25},
        })
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "STALE_VERSION"

    def test_update_params_validates_params(self, client, tmp_dir):
        """P1#2: Invalid params must be rejected with 422."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        orig_pv_id = store.get_latest_plan_version_id(plan_id)

        # max_bins=1 is invalid (must be >= 2)
        resp = client.post(f"/plans/{plan_id}/steps/fine-classing/params", json={
            "project_id": pid, "base_plan_version_id": orig_pv_id,
            "params": {"max_bins": 1},
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "PARAMS_VALIDATION_FAILED"


# ======================================================================
# Project Runs (Phase 3C)
# ======================================================================

class TestProjectRuns:
    def test_list_project_runs(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        resp = client.get(f"/projects/{pid}/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == pid
        assert isinstance(data["runs"], list)


# ======================================================================
# Project Artifacts (Phase 3D)
# ======================================================================

class TestProjectArtifacts:
    def test_list_project_artifacts(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        resp = client.get(f"/projects/{pid}/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == pid
        assert isinstance(data["artifacts"], list)

    def test_artifact_summary(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        import_resp = client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp = client.get(f"/artifacts/{artifact_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == artifact_id
        assert data["artifact_type"] == "dataset"

    def test_artifact_filters_by_run_id(self, client, tmp_dir, sample_german_credit):
        """P1#3: Filter project artifacts by run_id using run-step evidence."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        proof_plans = [p for p in store.get_plans_for_project(pid) if p["name"] == "Proof Pathway"]
        proof_pv_id = store.get_latest_plan_version_id(proof_plans[0]["plan_id"])

        run_resp = client.post("/runs", json={
            "project_id": pid, "plan_version_id": proof_pv_id,
        })
        assert run_resp.status_code == 201
        run_id = run_resp.json()["run_id"]

        # Filter by run_id
        resp = client.get(f"/projects/{pid}/artifacts?run_id={run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["artifacts"]) > 0

    def test_artifact_filters_by_producing_step(self, client, tmp_dir, sample_german_credit):
        """P1#3: Filter project artifacts by producing_step_id using run-step evidence."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        proof_plans = [p for p in store.get_plans_for_project(pid) if p["name"] == "Proof Pathway"]
        proof_pv_id = store.get_latest_plan_version_id(proof_plans[0]["plan_id"])
        client.post("/runs", json={"project_id": pid, "plan_version_id": proof_pv_id})

        # Filter by producing step ID (e.g. "split" produces train/test/oot artifacts in proof pathway)
        resp = client.get(f"/projects/{pid}/artifacts?producing_step_id=split")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["artifacts"]) > 0

    def test_json_artifact_summary(self, client, tmp_dir):
        """P2#4: JSON artifact summary reads via store.artifact_path()."""
        import json as jmod

        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        store = ProjectStore(proj_path)
        artifact = store.write_artifact_bytes(
            jmod.dumps({"score": 95, "rank": "A", "details": {"passed": 10, "failed": 0}}).encode(),
            artifact_type="report",
            role="report",
            filename="test.json",
            media_type="application/json",
        )

        resp = client.get(f"/artifacts/{artifact.artifact_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary_preview"] is not None
        assert data["summary_preview"]["score"] == 95

    def test_json_artifact_preview(self, client, tmp_dir):
        """P2#4: JSON artifact preview reads via store.artifact_path()."""
        import json as jmod

        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        store = ProjectStore(proj_path)
        artifact = store.write_artifact_bytes(
            jmod.dumps({"alpha": 1, "beta": 2, "gamma": 3}).encode(),
            artifact_type="report",
            role="report",
            filename="test.json",
            media_type="application/json",
        )

        resp = client.get(f"/artifacts/{artifact.artifact_id}/preview?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["media_type"] == "application/json"
        assert data["json_content"] is not None

    def test_artifact_preview(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        import_resp = client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp = client.get(f"/artifacts/{artifact_id}/preview?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == artifact_id
        assert data["media_type"] == "application/vnd.apache.parquet"
        assert isinstance(data["columns"], list)
        assert isinstance(data["rows"], list)


# ======================================================================
# Manual Binning Editor (Phase 3E)
# ======================================================================

class TestManualBinningEditor:
    def test_editor_state_requires_run(self, client, tmp_dir, sample_german_credit):
        """Without a run, the editor should be blocked."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]

        resp = client.get(f"/plans/{plan_id}/steps/manual-binning/editor-state?project_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["step_id"] == "manual-binning"
        # Without a run, should be blocked
        if not data["ready"]:
            assert data["blocked_reason"] is not None

    def test_preview_rejects_wrong_plan_version(self, client, tmp_dir):
        """P2#6: preview must reject plan_version_id not belonging to plan_id."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)

        # Get the scorecard plan's version
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]

        # Get a version from another plan (Proof Pathway)
        proof = [p for p in plans if p["name"] == "Proof Pathway"][0]
        proof_pv_id = store.get_latest_plan_version_id(proof["plan_id"])

        # Try previewing scorecard plan with proof plan's version
        resp = client.post(f"/plans/{plan_id}/steps/manual-binning/preview", json={
            "project_id": pid,
            "plan_version_id": proof_pv_id,
            "overrides": [],
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "VERSION_NOT_IN_PLAN"

    def test_preview_validates_override_structure(self, client, tmp_dir):
        """P2#5: malformed override bodies should produce 422 from FastAPI validation."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)

        # Send non-list overrides — should be a 422 from FastAPI (list expected)
        resp = client.post(f"/plans/{plan_id}/steps/manual-binning/preview", json={
            "project_id": pid,
            "plan_version_id": pv_id,
            "overrides": "not-a-list",
        })
        assert resp.status_code == 422

    def test_parquet_preview_pagination(self, client, tmp_dir, sample_german_credit):
        """P2#8: Parquet preview with offset reads correct rows."""
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        import_resp = client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp0 = client.get(f"/artifacts/{artifact_id}/preview?limit=1&offset=0")
        assert resp0.status_code == 200
        resp1 = client.get(f"/artifacts/{artifact_id}/preview?limit=1&offset=1")
        assert resp1.status_code == 200

        rows0 = resp0.json()["rows"]
        rows1 = resp1.json()["rows"]
        assert len(rows0) == 1
        assert len(rows1) == 1
        # Different offsets should return different rows (unless dataset has 1 row)
        if len(rows0) == 1 and len(rows1) == 1:
            assert rows0 != rows1, "Offset=0 and offset=1 must return different rows"


# ======================================================================
# Complete end-to-end flow with new endpoints
# ======================================================================

class TestE2EWithNewEndpoints:
    def test_full_flow_with_params_and_artifacts(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "full-flow-new.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Full Flow"}).json()
        pid = proj["project_id"]

        # Discover plans
        plans_resp = client.get(f"/projects/{pid}/plans")
        assert plans_resp.status_code == 200
        plans = plans_resp.json()["plans"]
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"]
        assert len(scorecard) == 1, "Scorecard Pathway must be discoverable"
        assert scorecard[0]["is_default"] is True
        plan_id = scorecard[0]["plan_id"]

        # Import dataset
        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        assert import_resp.status_code == 201

        # Run proof pathway to generate artifacts
        store = ProjectStore(proj_path)
        proof_plans = [p for p in store.get_plans_for_project(pid) if p["name"] == "Proof Pathway"]
        proof_pv_id = store.get_latest_plan_version_id(proof_plans[0]["plan_id"])

        run_resp = client.post("/runs", json={
            "project_id": pid, "plan_version_id": proof_pv_id,
        })
        assert run_resp.status_code == 201
        assert run_resp.json()["status"] == "succeeded"

        # List project runs
        runs_resp = client.get(f"/projects/{pid}/runs")
        assert runs_resp.status_code == 200
        assert len(runs_resp.json()["runs"]) >= 1

        # List project artifacts
        arts_resp = client.get(f"/projects/{pid}/artifacts")
        assert arts_resp.status_code == 200
        assert len(arts_resp.json()["artifacts"]) >= 1

        # Get artifact summary for first artifact
        artifacts = arts_resp.json()["artifacts"]
        summary_resp = client.get(f"/artifacts/{artifacts[0]['artifact_id']}/summary")
        assert summary_resp.status_code == 200

        # Preview first dataset artifact
        preview_resp = client.get(f"/artifacts/{artifacts[0]['artifact_id']}/preview?limit=3&offset=0")
        assert preview_resp.status_code == 200

        # Update step params
        scorecard_pv_id = store.get_latest_plan_version_id(plan_id)
        params_resp = client.post(f"/plans/{plan_id}/steps/fine-classing/params", json={
            "project_id": pid,
            "base_plan_version_id": scorecard_pv_id,
            "params": {"max_bins": 15},
        })
        assert params_resp.status_code == 200
        params_data = params_resp.json()
        assert params_data["changed_step_id"] == "fine-classing"

        # Check editor state
        editor_resp = client.get(f"/plans/{plan_id}/steps/manual-binning/editor-state?project_id={pid}")
        assert editor_resp.status_code == 200
