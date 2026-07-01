from __future__ import annotations

import pytest

from cardre.store import ProjectStore

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


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
