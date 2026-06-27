from __future__ import annotations

import pytest

from cardre.store import ProjectStore

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


class TestPlans:
    def test_get_proof_pathway_plan(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

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


class TestManifestOrdering:
    def test_scorecard_pathway_has_manifest_at_end(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
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

        resp = client.post(f"/plans/{plan_id}/steps/binning/params", json={
            "project_id": pid,
            "base_plan_version_id": orig_pv_id,
            "params": {"max_bins": 25, "min_bin_fraction": 0.03},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_id"] == plan_id
        assert data["new_plan_version_id"] != orig_pv_id
        assert data["changed_step_id"] == "binning"
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
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        v1_pv_id = store.get_latest_plan_version_id(plan_id)

        client.post(f"/plans/{plan_id}/steps/binning/params", json={
            "project_id": pid, "base_plan_version_id": v1_pv_id,
            "params": {"max_bins": 30},
        })

        resp = client.post(f"/plans/{plan_id}/steps/binning/params", json={
            "project_id": pid, "base_plan_version_id": v1_pv_id,
            "params": {"max_bins": 25},
        })
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "STALE_VERSION"

    def test_update_params_validates_params(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        orig_pv_id = store.get_latest_plan_version_id(plan_id)

        resp = client.post(f"/plans/{plan_id}/steps/binning/params", json={
            "project_id": pid, "base_plan_version_id": orig_pv_id,
            "params": {"max_bins": 1},
        })
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "PARAMS_VALIDATION_FAILED"
