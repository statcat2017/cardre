"""Sidecar API integration tests using FastAPI TestClient."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cardre.audit import StepSpec, json_logical_hash
from cardre.store import ProjectStore
from sidecar.main import app

# All 21 German Credit columns must be read as strings for scorecard compatibility.
# With proper CSV type inference polars converts numeric-looking fields (e.g.
# duration_months=6, credit_amount=1169) to Int64, breaking fine-classing/WOE
# which expects string-typed categorical bins.
_GERMAN_COLS_STR = {
    c: "str" for c in [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
}


pytest_plugins = []
pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_german_credit(tmp_dir):
    p = tmp_dir / "german_credit.csv"
    columns = [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
    header = ",".join(columns)
    rows = [
        "A11,6,A34,A43,1169,A65,A75,4,A93,A101,4,A121,67,A143,A152,2,A173,1,A192,A201,1",
        "A12,24,A32,A43,5951,A61,A73,2,A92,A101,4,A121,22,A142,A152,2,A173,1,A191,A201,2",
    ]
    p.write_text("\n".join([header] + rows))
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
        plans = store.get_plans_for_project(proj["project_id"])
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
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        client.post("/runs?sync=true", json={
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
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=plan_id, step_id="validate-target",
            base_plan_version_id=latest_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        latest_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=plan_id, step_id="split",
            base_plan_version_id=latest_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        latest_pv_id = _resp.new_plan_version_id

        resp = client.post("/runs?sync=true", json={
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
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=plan_id, step_id="validate-target",
            base_plan_version_id=latest_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        latest_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=plan_id, step_id="split",
            base_plan_version_id=latest_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        latest_pv_id = _resp.new_plan_version_id

        run_resp = client.post("/runs?sync=true", json={
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
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        # Run without importing data — the import step has no source_path
        # and should fail
        resp = client.post("/runs?sync=true", json={
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

    def test_get_run_steps(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        client.post("/datasets/import", json={
            "project_id": proj["project_id"], "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=plan_id, step_id="validate-target",
            base_plan_version_id=latest_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        latest_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=plan_id, step_id="split",
            base_plan_version_id=latest_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        latest_pv_id = _resp.new_plan_version_id

        run_resp = client.post("/runs?sync=true", json={
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
        plan_id = store.get_plans_for_project(pid)[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        # After import, the proof pathway should still have 6 steps
        pathway_steps = store.get_plan_version_steps(latest_pv_id)
        assert len(pathway_steps) == 6, f"Expected 6 pathway steps, got {len(pathway_steps)}"

        # Configure metadata for Proof Pathway
        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=plan_id, step_id="validate-target",
            base_plan_version_id=latest_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        latest_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=plan_id, step_id="split",
            base_plan_version_id=latest_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        latest_pv_id = _resp.new_plan_version_id

        run_resp = client.post("/runs?sync=true", json={
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

        resp = client.post("/runs?sync=true", json={
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
# Staleness Detail Endpoint (Task 4)
# ======================================================================

class TestStalenessDetailEndpoint:
    def test_staleness_endpoint(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "staleness-api.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Staleness API"}).json()
        pid = proj["project_id"]

        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(pid)[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=plan_id, step_id="validate-target",
            base_plan_version_id=latest_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        latest_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=plan_id, step_id="split",
            base_plan_version_id=latest_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        latest_pv_id = _resp.new_plan_version_id

        client.post("/runs?sync=true", json={
            "project_id": pid, "plan_version_id": latest_pv_id,
        })

        resp = client.get(f"/plans/{plan_id}/versions/{latest_pv_id}/staleness?project_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_version_id"] == latest_pv_id
        assert data["branch_id"] is None
        assert isinstance(data["nodes"], list)
        assert len(data["nodes"]) > 0
        for node in data["nodes"]:
            assert "step_id" in node
            assert "is_stale" in node
            assert "reason" in node
            assert node["is_stale"] is False
            assert node["reason"] is None

    def test_staleness_endpoint_wrong_plan_version(self, client, tmp_dir):
        proj_path = tmp_dir / "staleness-bad-version.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Staleness Bad"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        proof = [p for p in plans if p["name"] == "Proof Pathway"][0]
        proof_pv_id = store.get_latest_plan_version_id(proof["plan_id"])

        resp = client.get(f"/plans/{plan_id}/versions/{proof_pv_id}/staleness?project_id={pid}")
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "VERSION_NOT_IN_PLAN"

    def test_staleness_endpoint_not_found(self, client, tmp_dir):
        proj_path = tmp_dir / "staleness-not-found.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Staleness NF"}).json()
        pid = proj["project_id"]

        resp = client.get(f"/plans/nonexistent/versions/nonexistent/staleness?project_id={pid}")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PLAN_VERSION_NOT_FOUND"


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

        run_resp = client.post("/runs?sync=true", json={
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
        proof_plan_id = proof_plans[0]["plan_id"]
        proof_pv_id = store.get_latest_plan_version_id(proof_plan_id)

        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=proof_plan_id, step_id="validate-target",
            base_plan_version_id=proof_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        proof_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=proof_plan_id, step_id="split",
            base_plan_version_id=proof_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        proof_pv_id = _resp.new_plan_version_id

        client.post("/runs?sync=true", json={"project_id": pid, "plan_version_id": proof_pv_id})

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
        resp = client.post(f"/plans/{plan_id}/steps/manual-binning/manual-binning/preview", json={
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
        resp = client.post(f"/plans/{plan_id}/steps/manual-binning/manual-binning/preview", json={
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

        # Configure metadata for Proof Pathway before running
        store = ProjectStore(proj_path)
        proof_plans = [p for p in store.get_plans_for_project(pid) if p["name"] == "Proof Pathway"]
        proof_plan_id = proof_plans[0]["plan_id"]
        proof_pv_id = store.get_latest_plan_version_id(proof_plan_id)

        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=proof_plan_id, step_id="validate-target",
            base_plan_version_id=proof_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        proof_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=proof_plan_id, step_id="split",
            base_plan_version_id=proof_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        proof_pv_id = _resp.new_plan_version_id

        run_resp = client.post("/runs?sync=true", json={
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


@pytest.fixture
def larger_german_credit(tmp_dir):
    """~100 rows so the Scorecard Pathway can actually split + fine-class."""
    p = tmp_dir / "german_credit.csv"
    columns = [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
    # Base row with good credit risk
    good = "A11,6,A34,A43,1169,A65,A75,4,A93,A101,4,A121,67,A143,A152,2,A173,1,A192,A201,1"
    # Base row with bad credit risk
    bad = "A12,24,A32,A43,5951,A61,A73,2,A92,A101,4,A121,22,A142,A152,2,A173,1,A191,A201,2"
    lines = [",".join(columns)]
    # Generate ~50 good / ~50 bad with slight variations
    for i in range(50):
        parts_g = good.split(",")
        parts_g[0] = f"A{i % 11 + 11}"
        parts_g[1] = str(6 + (i % 48))
        parts_g[4] = str(1000 + i * 100)
        parts_g[10] = str(i % 4 + 1)
        parts_g[12] = str(20 + (i % 60))
        lines.append(",".join(parts_g))

        parts_b = bad.split(",")
        parts_b[0] = f"A{i % 11 + 11}"
        parts_b[1] = str(12 + (i % 36))
        parts_b[4] = str(2000 + i * 200)
        parts_b[10] = str(i % 4 + 1)
        parts_b[12] = str(25 + (i % 55))
        lines.append(",".join(parts_b))

    p.write_text("\n".join(lines))
    return p


class TestScorecardPathwayE2E:
    """End-to-end test of the Scorecard Pathway including run, params update,
    staleness correctness, manual-binning validation, and manifest ordering."""

    def test_scorecard_pathway_full_run(self, client, tmp_dir, larger_german_credit):
        proj_path = tmp_dir / "scorecard-e2e.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Scorecard E2E"}).json()
        pid = proj["project_id"]

        # 1. Discover the Scorecard Pathway
        plans_resp = client.get(f"/projects/{pid}/plans")
        assert plans_resp.status_code == 200
        plans = plans_resp.json()["plans"]
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"]
        assert len(scorecard) == 1
        assert scorecard[0]["is_default"] is True
        plan_id = scorecard[0]["plan_id"]

        # 2. Verify plan endpoint returns 23 steps with params
        plan_resp = client.get(f"/plans/{plan_id}?project_id={pid}")
        assert plan_resp.status_code == 200
        plan_data = plan_resp.json()
        assert len(plan_data["steps"]) == 23
        for step in plan_data["steps"]:
            assert "params" in step
            assert step["params"] is not None

        step_ids = [s["step_id"] for s in plan_data["steps"]]

        # Verify technical-manifest-stub is last
        assert step_ids[-1] == "technical-manifest-stub", (
            f"Expected technical-manifest-stub at end, got {step_ids[-1]}"
        )

        # 3. Import the larger dataset
        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(larger_german_credit),
            "dataset_id": "uci-statlog-german-credit",
            "schema_overrides": _GERMAN_COLS_STR,
        })
        assert import_resp.status_code == 201

        # 4. Configure modelling metadata and target_column (pathway now has empty defaults)
        store = ProjectStore(proj_path)
        pv_id = store.get_latest_plan_version_id(plan_id)
        meta_resp = client.post(f"/plans/{plan_id}/steps/define-metadata/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {
                "target_column": "credit_risk_class",
                "good_values": ["1"], "bad_values": ["2"],
                "indeterminate_values": [],
            },
        })
        assert meta_resp.status_code == 200
        pv_id = meta_resp.json()["new_plan_version_id"]

        # Also update validate-target and split's target_column
        vt_resp = client.post(f"/plans/{plan_id}/steps/validate-target/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {"target_column": "credit_risk_class"},
        })
        assert vt_resp.status_code == 200
        pv_id = vt_resp.json()["new_plan_version_id"]
        split_resp = client.post(f"/plans/{plan_id}/steps/split/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {
                "strategy": "random_stratified",
                "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                "target_column": "credit_risk_class", "role_column": None, "random_seed": 42,
            },
        })
        assert split_resp.status_code == 200
        pv_id = split_resp.json()["new_plan_version_id"]

        # 5. Run the Scorecard Pathway
        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid, "plan_version_id": pv_id,
        })
        assert run_resp.status_code == 201
        assert run_resp.json()["status"] == "succeeded", (
            f"Scorecard pathway run failed: {run_resp.json()}"
        )

        # 6. Update step params and verify staleness is scoped
        new_pv_id = store.get_latest_plan_version_id(plan_id)
        params_resp = client.post(f"/plans/{plan_id}/steps/fine-classing/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id,
            "params": {"max_bins": 15},
        })
        assert params_resp.status_code == 200
        params_data = params_resp.json()
        assert params_data["changed_step_id"] == "fine-classing"

        # Stale should only include fine-classing + its descendants,
        # NOT e.g. import, define-modelling-metadata, apply-exclusions, etc.
        stale_ids = set(params_data["stale_step_ids"])
        assert "fine-classing" in stale_ids
        non_stale_ancestors = {"import", "define-modelling-metadata", "apply-exclusions",
                                "development-sample-definition", "split"}
        for anc in non_stale_ancestors:
            assert anc not in stale_ids, (
                f"Unchanged ancestor {anc} should not be stale after fine-classing param update"
            )

        # 6. Manual-binning save with invalid overrides is rejected
        new_pv_id2 = store.get_latest_plan_version_id(plan_id)
        bad_override_resp = client.post(f"/plans/{plan_id}/steps/manual-binning/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id2,
            "params": {
                "overrides": [
                    {
                        "variable": "age_years",
                        "action": "merge_bins",
                        "source_bin_ids": ["nonexistent_bin"],
                        "reason": "testing validation",
                    }
                ],
            },
        })
        assert bad_override_resp.status_code == 422, (
            f"Expected 422 for invalid bin ID, got {bad_override_resp.status_code}: {bad_override_resp.json()}"
        )

        # 7. Manual-binning save for non-selected variable is rejected (#9/#13)
        unselected_resp = client.post(f"/plans/{plan_id}/steps/manual-binning/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id2,
            "params": {
                "overrides": [{"variable": "age_years", "action": "merge_bins",
                              "source_bin_ids": ["age_years_bin_001", "age_years_bin_002"],
                              "reason": "test merge"}],
            },
        })
        assert unselected_resp.status_code == 422, (
            f"Expected 422 for non-selected variable, "
            f"got {unselected_resp.status_code}: {unselected_resp.json()}"
        )
        assert "not selected by variable-selection" in unselected_resp.json()["detail"]["message"]

        # 8. Manual-binning save works for a selected variable (pick from editor state)
        es_resp = client.get(f"/plans/{plan_id}/steps/manual-binning/editor-state?project_id={pid}")
        if es_resp.status_code == 200 and es_resp.json().get("selected_variables"):
            selected_var = es_resp.json()["selected_variables"][0]
            es = es_resp.json()
            source_bins = es.get("source_bins_by_variable", {})
            var_bins = source_bins.get(selected_var, {})
            bins = var_bins.get("bins", [])
            if len(bins) >= 2:
                bin_ids = [b["bin_id"] for b in bins[:2]]
                save_resp = client.post(f"/plans/{plan_id}/steps/manual-binning/params", json={
                    "project_id": pid,
                    "base_plan_version_id": new_pv_id2,
                    "params": {
                        "overrides": [{"variable": selected_var, "action": "merge_bins",
                                      "source_bin_ids": bin_ids,
                                      "reason": "test merge selected"}],
                    },
                })
                assert save_resp.status_code == 200, (
                    f"Expected 200 for selected variable override, "
                    f"got {save_resp.status_code}: {save_resp.json()}"
                )

    def test_manual_binning_save_rejected_without_upstream_run(self, client, tmp_dir, larger_german_credit):
        """Manual-binning save without any successful run is rejected."""
        proj_path = tmp_dir / "no-run-mb.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "No Run MB"}).json()
        pid = proj["project_id"]

        plans_resp = client.get(f"/projects/{pid}/plans")
        scorecard = [p for p in plans_resp.json()["plans"] if p["name"] == "Scorecard Pathway"]
        plan_id = scorecard[0]["plan_id"]

        store = ProjectStore(proj_path)
        pv_id = store.get_latest_plan_version_id(plan_id)

        resp = client.post(f"/plans/{plan_id}/steps/manual-binning/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {
                "overrides": [{"variable": "age_years", "action": "merge_bins",
                              "source_bin_ids": ["age_years_bin_001", "age_years_bin_002"],
                              "reason": "test"}],
            },
        })
        assert resp.status_code == 422, (
            f"Expected 422 without any successful run, got {resp.status_code}: {resp.json()}"
        )
        assert "Run fine-classing" in resp.json()["detail"]["message"]

    def test_staleness_and_status_after_param_update(self, client, tmp_dir, larger_german_credit):
        """Regression test: after a param update, unchanged upstream steps
        must be non-stale and show their previous run status, while
        changed descendants are stale and show 'not_run'."""
        proj_path = tmp_dir / "staleness-regression.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Staleness Test"}).json()
        pid = proj["project_id"]

        # Discover Scorecard Pathway
        plans_resp = client.get(f"/projects/{pid}/plans")
        scorecard = [p for p in plans_resp.json()["plans"] if p["name"] == "Scorecard Pathway"]
        plan_id = scorecard[0]["plan_id"]

        # Import dataset
        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(larger_german_credit),
            "dataset_id": "uci-statlog-german-credit",
            "schema_overrides": _GERMAN_COLS_STR,
        })

        # Configure modelling metadata and target_column
        store = ProjectStore(proj_path)
        pv_id = store.get_latest_plan_version_id(plan_id)
        meta_resp = client.post(f"/plans/{plan_id}/steps/define-metadata/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {
                "target_column": "credit_risk_class",
                "good_values": ["1"], "bad_values": ["2"],
                "indeterminate_values": [],
            },
        })
        assert meta_resp.status_code == 200
        pv_id = meta_resp.json()["new_plan_version_id"]

        vt_resp = client.post(f"/plans/{plan_id}/steps/validate-target/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {"target_column": "credit_risk_class"},
        })
        assert vt_resp.status_code == 200
        pv_id = vt_resp.json()["new_plan_version_id"]
        split_resp = client.post(f"/plans/{plan_id}/steps/split/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {
                "strategy": "random_stratified",
                "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                "target_column": "credit_risk_class", "role_column": None, "random_seed": 42,
            },
        })
        assert split_resp.status_code == 200
        pv_id = split_resp.json()["new_plan_version_id"]

        # Run the Scorecard Pathway
        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid, "plan_version_id": pv_id,
        })
        assert run_resp.status_code == 201
        assert run_resp.json()["status"] == "succeeded"

        # Update fine-classing params
        new_pv_id = store.get_latest_plan_version_id(plan_id)
        params_resp = client.post(f"/plans/{plan_id}/steps/fine-classing/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id,
            "params": {"max_bins": 12},
        })
        assert params_resp.status_code == 200

        # GET /plans/{plan_id} — staleness and statuses should be consistent
        plan_resp = client.get(f"/plans/{plan_id}?project_id={pid}")
        assert plan_resp.status_code == 200
        plan_data = plan_resp.json()
        steps_map = {s["step_id"]: s for s in plan_data["steps"]}

        # Unchanged upstream steps: non-stale, status from previous run
        non_stale_upstream = ["import", "define-metadata", "apply-exclusions",
                              "profile", "validate-target", "sample-definition",
                              "split", "explicit-missing-outlier-treatment"]
        for step_id in non_stale_upstream:
            s = steps_map[step_id]
            assert not s["is_stale"], f"{step_id} should not be stale"
            assert s["status"] == "succeeded", (
                f"{step_id} should show 'succeeded' (carried forward), got {s['status']!r}"
            )

        # The changed step is stale
        assert steps_map["fine-classing"]["is_stale"]
        # Its transitive descendants are stale
        stale_downstream = ["initial-woe-iv", "variable-clustering", "variable-selection",
                            "manual-binning", "final-woe-iv", "woe-transform-train",
                            "logistic-regression", "score-scaling", "build-summary-report",
                            "apply-woe", "apply-model",
                            "validation-metrics", "cutoff-analysis", "technical-manifest-stub"]
        for step_id in stale_downstream:
            s = steps_map[step_id]
            assert s["is_stale"], f"{step_id} should be stale (descendant of fine-classing)"
            # Stale steps should show "not_run" (no run on new version for them)
            assert s["status"] == "not_run", (
                f"{step_id} should show 'not_run' (stale), got {s['status']!r}"
            )


# ======================================================================
# Phase 4 E2E: Branching, Comparison, Champion, Export
# ======================================================================

class TestPhase4BranchingFlow:

    def test_full_branch_flow(self, client, tmp_dir, larger_german_credit):
        """Complete Phase 4 branch flow:
        create/import/run baseline
        -> migrate baseline branch
        -> create manual-binning challenger
        -> edit challenger params
        -> confirm branch head updated
        -> run challenger branch
        -> confirm shared upstream evidence consumed
        -> confirm baseline staleness unchanged
        -> create and refresh comparison
        -> confirm comparison sections populated
        -> assign champion from ready snapshot
        -> export with include_row_level_data=False
        -> assert no row-level Parquet dataset artifacts in export
        """
        proj_path = tmp_dir / "test_phase4_e2e.cardre"

        # 1. Create project
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Phase4E2E"}).json()
        pid = proj["project_id"]
        store = ProjectStore(proj_path)

        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]

        # 2. Import German Credit
        imp_resp = client.post("/datasets/import", json={
            "project_id": pid,
            "source_path": str(larger_german_credit),
            "dataset_id": "uci-statlog-german-credit",
            "schema_overrides": _GERMAN_COLS_STR,
        })
        assert imp_resp.status_code in (200, 201)

        # 3. Configure modelling metadata and target_column
        plan_resp = client.get(f"/plans/{plan_id}?project_id={pid}")
        assert plan_resp.status_code == 200
        pv_id = plan_resp.json()["latest_version_id"]
        meta_resp = client.post(f"/plans/{plan_id}/steps/define-metadata/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {
                "target_column": "credit_risk_class",
                "good_values": ["1"], "bad_values": ["2"],
                "indeterminate_values": [],
            },
        })
        assert meta_resp.status_code == 200
        pv_id = meta_resp.json()["new_plan_version_id"]

        vt_resp = client.post(f"/plans/{plan_id}/steps/validate-target/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {"target_column": "credit_risk_class"},
        })
        assert vt_resp.status_code == 200
        pv_id = vt_resp.json()["new_plan_version_id"]
        split_resp = client.post(f"/plans/{plan_id}/steps/split/params", json={
            "project_id": pid,
            "base_plan_version_id": pv_id,
            "params": {
                "strategy": "random_stratified",
                "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                "target_column": "credit_risk_class", "role_column": None, "random_seed": 42,
            },
        })
        assert split_resp.status_code == 200
        pv_id = split_resp.json()["new_plan_version_id"]

        # 4. Run full scorecard pathway
        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": pv_id,
        })
        assert run_resp.status_code == 201, f"Run failed: {run_resp.json()}"
        run_data = run_resp.json()
        assert run_data["status"] == "succeeded", f"Run did not succeed: {run_data}"

        # 5. Migrate baseline branch
        mig_resp = client.post("/migrations/baseline", json={"project_id": pid})
        assert mig_resp.status_code == 200
        mig_data = mig_resp.json()
        assert mig_data["branches_created"] >= 1

        # 6. Get baseline branch ID for the Scorecard Pathway
        branches_resp = client.get(f"/projects/{pid}/branches?plan_id={plan_id}")
        assert branches_resp.status_code == 200
        branches = branches_resp.json()["branches"]
        baseline_branches = [b for b in branches if b["branch_type"] == "baseline"]
        assert len(baseline_branches) >= 1, f"No baseline branch for plan {plan_id}. Branches: {branches}"
        baseline_branch_id = baseline_branches[0]["branch_id"]

        # 7. Create manual-binning challenger branch
        baseline_detail = client.get(f"/branches/{baseline_branch_id}?project_id={pid}")
        assert baseline_detail.status_code == 200
        base_pv_id = baseline_detail.json()["head_plan_version_id"]

        # Verify the plan version has manual-binning step
        pv_steps = store.get_plan_version_steps(base_pv_id)
        step_ids = [s.step_id for s in pv_steps]
        assert "manual-binning" in step_ids, (
            f"manual-binning not found in plan version {base_pv_id}. "
            f"Available steps: {step_ids}"
        )

        branch_resp = client.post(f"/plans/{plan_id}/branches", json={
            "project_id": pid,
            "name": "Coarser bins",
            "branch_type": "binning_challenger",
            "branch_point_step_id": "manual-binning",
            "base_branch_id": baseline_branch_id,
            "base_plan_version_id": base_pv_id,
            "created_reason": "Testing challenger branch creation.",
        })
        assert branch_resp.status_code == 201, f"Branch creation failed: {branch_resp.json()}"
        branch_data = branch_resp.json()
        branch_id = branch_data["branch_id"]
        assert branch_id != baseline_branch_id
        assert "manual-binning" in branch_data["created_step_ids"]
        manual_binning_step_id = branch_data["created_step_ids"]["manual-binning"]
        assert "__" in manual_binning_step_id
        new_pv_id = branch_data["new_plan_version_id"]

        # 8. Verify branch head plan version is the new version
        branch_detail = client.get(f"/branches/{branch_id}?project_id={pid}")
        assert branch_detail.status_code == 200
        assert branch_detail.json()["head_plan_version_id"] == new_pv_id

        # 8. Edit challenger manual-binning params
        params_resp = client.post(f"/plans/{plan_id}/steps/{manual_binning_step_id}/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id,
            "params": {"overrides": []},
        })
        assert params_resp.status_code == 200, f"Param edit failed: {params_resp.json()}"
        params_data = params_resp.json()
        updated_pv_id = params_data["new_plan_version_id"]

        # 9. Confirm branch head updated after param edit
        branch_after = client.get(f"/branches/{branch_id}?project_id={pid}")
        assert branch_after.status_code == 200
        assert branch_after.json()["head_plan_version_id"] == updated_pv_id

        # 10. Run challenger branch
        run_branch_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": updated_pv_id,
            "run_scope": "branch",
            "branch_id": branch_id,
        })
        assert run_branch_resp.status_code == 201, f"Branch run failed: {run_branch_resp.json()}"
        br_data = run_branch_resp.json()
        assert br_data["status"] == "succeeded", f"Branch run did not succeed: {br_data}"

        # 11. Confirm branch-scoped run has correct branch_id
        assert br_data["branch_id"] == branch_id
        assert len(br_data["executed_step_ids"]) > 0
        # Baseline full-plan run should still have no branch_id
        assert run_data.get("branch_id") is None
        plan_after = client.get(f"/plans/{plan_id}?project_id={pid}")
        assert plan_after.status_code == 200
        base_branch_detail = client.get(f"/branches/{baseline_branch_id}?project_id={pid}")
        assert base_branch_detail.status_code == 200
        # The plan-level response shows staleness against full-plan (branch_id=NULL)
        # evidence, not branch-scoped. Branch-specific evidence is verified via
        # the branch run's own records and the comparison snapshot below.

        # Second branch run should succeed (not false-stale on shared upstream)
        run_branch2_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": updated_pv_id,
            "run_scope": "branch",
            "branch_id": branch_id,
        })
        assert run_branch2_resp.status_code == 201, f"Second branch run failed: {run_branch2_resp.json()}"
        br2_data = run_branch2_resp.json()
        assert br2_data["status"] == "succeeded", f"Second branch run did not succeed: {br2_data}"

        # Third branch run: since the second was a no-op (all steps already current),
        # this should still succeed and return the same run_id as the second.
        run_branch3_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": updated_pv_id,
            "run_scope": "branch",
            "branch_id": branch_id,
        })
        assert run_branch3_resp.status_code == 201, f"Third branch run failed: {run_branch3_resp.json()}"
        br3_data = run_branch3_resp.json()
        assert br3_data["status"] == "succeeded", f"Third branch run did not succeed: {br3_data}"
        # Third run should return the same run_id as the second (no-op short-circuit)
        assert br3_data["run_id"] == br2_data["run_id"], (
            f"No-op branch run should return same run_id as prior successful run. "
            f"Got {br3_data['run_id']}, expected {br2_data['run_id']}"
        )

        # 12. Create comparison intent
        comp_resp = client.post("/branch-comparisons", json={
            "project_id": pid,
            "plan_id": plan_id,
            "baseline_branch_id": baseline_branch_id,
            "challenger_branch_ids": [branch_id],
            "comparison_spec": {
                "roles": ["train", "test", "oot"],
                "include_woe_iv": True,
                "include_model": True,
                "include_validation": True,
                "include_cutoff": True,
                "include_warnings": True,
            },
            "created_reason": "E2E test comparison.",
        })
        assert comp_resp.status_code == 201, f"Comparison creation failed: {comp_resp.json()}"
        comp_id = comp_resp.json()["comparison_id"]

        # 13. Refresh comparison
        refresh_resp = client.post(f"/branch-comparisons/{comp_id}/refresh")
        assert refresh_resp.status_code == 200, f"Comparison refresh failed: {refresh_resp.json()}"
        refresh_data = refresh_resp.json()
        assert refresh_data["ready"], f"Comparison not ready: {refresh_data.get('blocked_reason')}"
        assert refresh_data["comparison_snapshot_id"] is not None

        # 14. Verify comparison snapshot content
        snap_resp = client.get(f"/branch-comparison-snapshots/{refresh_data['comparison_snapshot_id']}")
        assert snap_resp.status_code == 200
        snap_data = snap_resp.json()
        assert snap_data["ready"]

        # Read snapshot artifact to verify content sections
        artifact_resp = client.get(f"/artifacts/{snap_data['comparison_artifact_id']}")
        if artifact_resp.status_code == 200:
            art_path = artifact_resp.json()["path"]
            art_full_path = proj_path / art_path
            if art_full_path.exists():
                comp_content = json.loads(art_full_path.read_text())
                assert "woe_iv" in comp_content
                assert "model" in comp_content
                assert "validation" in comp_content
                assert "cutoff" in comp_content
                # Assert sections exist with baseline and challenger content
                assert isinstance(comp_content["woe_iv"].get("variables"), list)
                assert isinstance(comp_content["model"]["branch_level"], dict)
                assert isinstance(comp_content["validation"]["roles"], dict)
                assert isinstance(comp_content["cutoff"]["roles"], dict)
                # Baseline and challenger should have entries
                assert "baseline" in comp_content["model"]["branch_level"] or comp_content["model"]["branch_level"] != {}
                for role_name in ("train", "test", "oot"):
                    role_data = comp_content["validation"]["roles"].get(role_name, {})
                    if role_data:
                        assert "baseline" in role_data or branch_id in role_data

        # 15. Assign champion
        champ_resp = client.post(f"/plans/{plan_id}/champion", json={
            "project_id": pid,
            "branch_id": branch_id,
            "comparison_id": comp_id,
            "comparison_snapshot_id": refresh_data["comparison_snapshot_id"],
            "scope_type": "project",
            "scope_key": "default",
            "assigned_reason": "Challenger has coarser bins with minimal IV loss.",
        })
        assert champ_resp.status_code == 201, f"Champion assignment failed: {champ_resp.json()}"
        champ_data = champ_resp.json()
        assert champ_data["champion_branch_id"] == branch_id
        assert champ_data["previous_champion_branch_id"] is None  # First champion

        # 16. Reassign champion (supersedes previous)
        champ2_resp = client.post(f"/plans/{plan_id}/champion", json={
            "project_id": pid,
            "branch_id": baseline_branch_id,
            "comparison_id": comp_id,
            "comparison_snapshot_id": refresh_data["comparison_snapshot_id"],
            "scope_type": "project",
            "scope_key": "default",
            "assigned_reason": "Switching back to baseline for comparison.",
        })
        assert champ2_resp.status_code == 201
        assert champ2_resp.json()["previous_champion_branch_id"] is not None

        # 17. Export with include_row_level_data=False
        export_dest = proj_path / "exports" / "e2e_export"
        export_resp = client.post("/exports/audit-pack", json={
            "project_id": pid,
            "plan_id": plan_id,
            "branch_id": branch_id,
            "comparison_id": comp_id,
            "comparison_snapshot_id": refresh_data["comparison_snapshot_id"],
            "include_row_level_data": False,
            "export_path": str(export_dest),
        })
        assert export_resp.status_code == 200, f"Export failed: {export_resp.json()}"
        export_data = export_resp.json()
        assert export_data["file_count"] > 0

        # 18. Assert no row-level Parquet dataset artifacts in export
        export_path = Path(export_data["export_path"])
        artifacts_meta = export_path / "artifacts.json"
        assert artifacts_meta.exists()
        exported_artifacts = json.loads(artifacts_meta.read_text())
        for art in exported_artifacts:
            assert art["artifact_type"] not in ("dataset", "tabular"), (
                f"Row-level artifact {art['artifact_id']} of type {art['artifact_type']} "
                f"should not be in export when include_row_level_data=False"
            )

        # Verify export includes shared-upstream run-step evidence
        run_steps_file = export_path / "run_steps.json"
        assert run_steps_file.exists()
        exported_run_steps = json.loads(run_steps_file.read_text())
        exported_step_ids = {rs["step_id"] for rs in exported_run_steps}
        # Should have both branch-owned steps AND shared upstream steps
        has_shared = any("import" in sid or "define-metadata" in sid for sid in exported_step_ids)
        assert has_shared, f"Export should include shared-upstream run steps, got: {exported_step_ids}"

        # 19. Export with include_row_level_data=True to verify it includes datasets
        export_dest2 = proj_path / "exports" / "e2e_export_full"
        export2_resp = client.post("/exports/audit-pack", json={
            "project_id": pid,
            "plan_id": plan_id,
            "branch_id": branch_id,
            "include_row_level_data": True,
            "export_path": str(export_dest2),
        })
        assert export2_resp.status_code == 200
        export2_data = export2_resp.json()
        artifacts_meta2 = Path(export2_data["export_path"]) / "artifacts.json"
        exported_artifacts2 = json.loads(artifacts_meta2.read_text())
        has_dataset = any(a["artifact_type"] in ("dataset", "tabular") for a in exported_artifacts2)
        assert has_dataset, "Full export should include dataset artifacts"

        # 20. Verify champion query works
        get_champ_resp = client.get(f"/plans/{plan_id}/champion?project_id={pid}")
        assert get_champ_resp.status_code == 200


# ======================================================================
# Wave 2: Cancel + Manifest
# ======================================================================

class TestCancelAndManifest:

    def test_cancel_endpoint(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "cancel-test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Cancel Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(pid)[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        run_id = store.create_run(latest_pv_id)

        resp = client.post(f"/runs/{run_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "cancelling"

    def test_manifest_endpoint(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "manifest-test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Manifest Test"}).json()
        pid = proj["project_id"]
        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(pid)[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        from cardre.services.plan_service import PlanService
        ps = PlanService(store)
        _resp = ps.update_params(
            plan_id=plan_id, step_id="validate-target",
            base_plan_version_id=latest_pv_id,
            params={"target_column": "credit_risk_class"},
        )
        latest_pv_id = _resp.new_plan_version_id
        _resp = ps.update_params(
            plan_id=plan_id, step_id="split",
            base_plan_version_id=latest_pv_id,
            params={
                "train_fraction": 0.6, "test_fraction": 0.2,
                "oot_fraction": 0.2, "strategy": "random_stratified",
                "target_column": "credit_risk_class", "role_column": None,
                "random_seed": 42,
            },
        )
        latest_pv_id = _resp.new_plan_version_id

        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid, "plan_version_id": latest_pv_id,
        })
        assert run_resp.status_code == 201
        run_id = run_resp.json()["run_id"]

        manifest_resp = client.get(f"/runs/{run_id}/manifest")
        assert manifest_resp.status_code == 200
        manifest = manifest_resp.json()
        assert manifest["manifest_version"] == "1.0.0"
        assert manifest["run_id"] == run_id
        assert manifest["plan_version_id"] == latest_pv_id
        assert manifest["execution_mode"] == "full"
        assert isinstance(manifest["steps"], list)
        assert len(manifest["steps"]) > 0
        for step in manifest["steps"]:
            assert "step_id" in step
            assert "node_type" in step
            assert "status" in step
            assert "execution_fingerprint" in step

