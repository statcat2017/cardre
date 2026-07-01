from __future__ import annotations

import pytest

from cardre.store import ProjectStore

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


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

        resp = client.get(f"/runs/project/{proj['project_id']}/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "succeeded"

    def test_run_failure_path(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        resp = client.post("/runs?sync=true", json={
            "project_id": proj["project_id"],
            "plan_version_id": latest_pv_id,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "failed"

        all_runs = store.list_runs(data["plan_version_id"])
        matching = [r for r in all_runs if r["run_id"] == data["run_id"]]
        assert len(matching) == 1, "Expected exactly one run record for the failed run"

    def test_concurrent_run_returns_409(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)

        running_run_id = store.create_run(pv_id)
        assert running_run_id is not None

        resp = client.post("/runs", json={
            "project_id": proj["project_id"],
            "plan_version_id": pv_id,
        })
        assert resp.status_code == 409
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "CONCURRENT_RUN"

        store.finish_run(running_run_id, "failed")

    def test_stale_run_not_recovered_by_get(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(pid)[0]["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)

        run_id = store.create_run(pv_id)
        old_ts = "2020-01-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?",
            (old_ts, run_id),
        )
        store._connect().commit()

        resp = client.get(f"/runs/project/{pid}/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running", (
            f"GET /runs/project/{pid}/runs/{run_id} should return status=running, got {data['status']}"
        )
        assert data["is_stale"] is True, "stale run should be flagged is_stale"

        run = store.get_run(run_id)
        assert run["status"] == "running", "GET must not change run status"

        store.finish_run(run_id, "failed")

    def test_stale_run_recovered_before_create_run(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(proj["project_id"])[0]["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)

        stale_run_id = store.create_run(pv_id)
        old_ts = "2020-01-01T00:00:00"
        store._connect().execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?",
            (old_ts, stale_run_id),
        )
        store._connect().commit()

        resp = client.post("/runs", json={
            "project_id": proj["project_id"],
            "plan_version_id": pv_id,
        })
        assert resp.status_code == 201, (
            f"Expected 201 after stale recovery, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert data["run_id"] != stale_run_id, "must create a new run ID"

        stale = store.get_run(stale_run_id)
        assert stale["status"] == "interrupted", (
            f"Stale run should be interrupted, got {stale['status']}"
        )

        diags = store.get_run_diagnostics(stale_run_id)
        codes = [d.get("code") for d in diags]
        assert "RUN_RECOVERED_STALE" in codes, (
            "Stale recovery should append RUN_RECOVERED_STALE diagnostic"
        )

        store.finish_run(data["run_id"], "failed")
        store._connect().close()

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

        resp = client.get(f"/runs/project/{proj['project_id']}/runs/{run_id}/steps")
        assert resp.status_code == 200
        steps = resp.json()["steps"]
        assert len(steps) > 0
        for step in steps:
            assert step["status"] in ("succeeded", "failed")


class TestCancelAndManifest:
    def test_cancel_endpoint_returns_404(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "cancel-test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Cancel Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plan_id = store.get_plans_for_project(pid)[0]["plan_id"]
        latest_pv_id = store.get_latest_plan_version_id(plan_id)

        run_id = store.create_run(latest_pv_id)

        resp = client.post(f"/runs/{run_id}/cancel")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

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

        manifest_resp = client.get(f"/runs/project/{pid}/runs/{run_id}/manifest")
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
