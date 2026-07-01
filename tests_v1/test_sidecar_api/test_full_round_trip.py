from __future__ import annotations

import pytest

from cardre.audit import StepSpec, json_logical_hash
from cardre.store import ProjectStore

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


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

        pathway_steps = store.get_plan_version_steps(latest_pv_id)
        assert len(pathway_steps) == 6, f"Expected 6 pathway steps, got {len(pathway_steps)}"

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

        steps_resp = client.get(f"/runs/project/{pid}/runs/{run_id}/steps")
        assert steps_resp.status_code == 200
        steps = steps_resp.json()["steps"]
        assert len(steps) == 6, f"Expected 6 run steps, got {len(steps)}"
        assert all(s["status"] == "succeeded" for s in steps)

        plan_resp = client.get(f"/plans/{plan_id}")
        assert plan_resp.status_code == 200
        assert all(s["is_stale"] is False for s in plan_resp.json()["steps"])
        assert len(plan_resp.json()["steps"]) == 6

    def test_import_does_not_overwrite_proof_pathway(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)

        plans_before = store.get_plans_for_project(pid)
        proof_before = [p for p in plans_before if p["name"] == "Proof Pathway"]
        assert len(proof_before) == 1
        proof_plan_id = proof_before[0]["plan_id"]

        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })

        plans_after = store.get_plans_for_project(pid)

        proof_after = [p for p in plans_after if p["name"] == "Proof Pathway"]
        assert len(proof_after) == 1
        latest_pv_id = store.get_latest_plan_version_id(proof_after[0]["plan_id"])
        assert latest_pv_id is not None
        steps = store.get_plan_version_steps(latest_pv_id)
        assert len(steps) == 6, f"Proof pathway has {len(steps)} steps, expected 6"

        import_plans = [p for p in plans_after if p["name"] == "__import__"]
        assert len(import_plans) == 1, "Expected __import__ plan to exist after import"
        assert import_plans[0]["plan_id"] != proof_plan_id, "Import plan must be distinct from proof pathway"

    def test_unknown_node_type_produces_failed_run(self, client, tmp_dir, sample_german_credit):
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

        steps_resp = client.get(f"/runs/project/{pid}/runs/{data['run_id']}/steps")
        assert steps_resp.status_code == 200
        steps = steps_resp.json()["steps"]
        assert len(steps) > 0
        has_error = any(len(s.get("errors", [])) > 0 for s in steps)
        assert has_error, "Expected at least one step with structured error evidence"


class TestE2EWithNewEndpoints:
    def test_full_flow_with_params_and_artifacts(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "full-flow-new.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Full Flow"}).json()
        pid = proj["project_id"]

        plans_resp = client.get(f"/projects/{pid}/plans")
        assert plans_resp.status_code == 200
        plans = plans_resp.json()["plans"]
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"]
        assert len(scorecard) == 1, "Scorecard Pathway must be discoverable"
        assert scorecard[0]["is_default"] is True
        plan_id = scorecard[0]["plan_id"]

        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        assert import_resp.status_code == 201

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

        runs_resp = client.get(f"/projects/{pid}/runs")
        assert runs_resp.status_code == 200
        assert len(runs_resp.json()["runs"]) >= 1

        arts_resp = client.get(f"/projects/{pid}/artifacts")
        assert arts_resp.status_code == 200
        assert len(arts_resp.json()["artifacts"]) >= 1

        artifacts = arts_resp.json()["artifacts"]
        summary_resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifacts[0]['artifact_id']}/summary")
        assert summary_resp.status_code == 200

        preview_resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifacts[0]['artifact_id']}/preview?limit=3&offset=0")
        assert preview_resp.status_code == 200

        scorecard_pv_id = store.get_latest_plan_version_id(plan_id)
        params_resp = client.post(f"/plans/{plan_id}/steps/binning/params", json={
            "project_id": pid,
            "base_plan_version_id": scorecard_pv_id,
            "params": {"max_bins": 15},
        })
        assert params_resp.status_code == 200
        params_data = params_resp.json()
        assert params_data["changed_step_id"] == "binning"

        editor_resp = client.get(f"/plans/{plan_id}/steps/manual-binning/editor-state?project_id={pid}")
        assert editor_resp.status_code == 200
