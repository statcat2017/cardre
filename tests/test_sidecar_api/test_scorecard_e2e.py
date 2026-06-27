from __future__ import annotations

import pytest

from cardre.store import ProjectStore
from tests.test_sidecar_api.conftest import _GERMAN_COLS_STR

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


class TestScorecardPathwayE2E:

    def test_scorecard_pathway_full_run(self, client, tmp_dir, larger_german_credit):
        proj_path = tmp_dir / "scorecard-e2e.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Scorecard E2E"}).json()
        pid = proj["project_id"]

        plans_resp = client.get(f"/projects/{pid}/plans")
        assert plans_resp.status_code == 200
        plans = plans_resp.json()["plans"]
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"]
        assert len(scorecard) == 1
        assert scorecard[0]["is_default"] is True
        plan_id = scorecard[0]["plan_id"]

        plan_resp = client.get(f"/plans/{plan_id}?project_id={pid}")
        assert plan_resp.status_code == 200
        plan_data = plan_resp.json()
        assert len(plan_data["steps"]) == 24
        for step in plan_data["steps"]:
            assert "params" in step
            assert step["params"] is not None

        step_ids = [s["step_id"] for s in plan_data["steps"]]

        assert step_ids[-1] == "technical-manifest-stub", (
            f"Expected technical-manifest-stub at end, got {step_ids[-1]}"
        )

        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(larger_german_credit),
            "dataset_id": "uci-statlog-german-credit",
            "schema_overrides": _GERMAN_COLS_STR,
        })
        assert import_resp.status_code == 201

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

        aw_resp = client.post(f"/plans/{plan_id}/steps/apply-woe/params", json={
            "project_id": pid, "base_plan_version_id": pv_id,
            "params": {"woe_unmatched_policy": "warn"},
        })
        assert aw_resp.status_code == 200
        pv_id = aw_resp.json()["new_plan_version_id"]

        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid, "plan_version_id": pv_id,
        })
        assert run_resp.status_code == 201
        assert run_resp.json()["status"] == "succeeded", (
            f"Scorecard pathway run failed: {run_resp.json()}"
        )

        new_pv_id = store.get_latest_plan_version_id(plan_id)
        params_resp = client.post(f"/plans/{plan_id}/steps/binning/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id,
            "params": {"max_bins": 15},
        })
        assert params_resp.status_code == 200
        params_data = params_resp.json()
        assert params_data["changed_step_id"] == "binning"

        stale_ids = set(params_data["stale_step_ids"])
        assert "binning" in stale_ids
        non_stale_ancestors = {"import", "define-modelling-metadata", "apply-exclusions",
                                "development-sample-definition", "split"}
        for anc in non_stale_ancestors:
            assert anc not in stale_ids, (
                f"Unchanged ancestor {anc} should not be stale after binning param update"
            )

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
        assert bad_override_resp.status_code == 400, (
            f"Expected 400 for invalid bin ID, got {bad_override_resp.status_code}: {bad_override_resp.json()}"
        )

        unselected_resp = client.post(f"/plans/{plan_id}/steps/manual-binning/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id2,
            "params": {
                "overrides": [{"variable": "age_years", "action": "merge_bins",
                              "source_bin_ids": ["age_years_bin_001", "age_years_bin_002"],
                              "reason": "test merge"}],
            },
        })
        assert unselected_resp.status_code == 400, (
            f"Expected 400 for non-selected variable, "
            f"got {unselected_resp.status_code}: {unselected_resp.json()}"
        )
        assert "not selected by variable-selection" in unselected_resp.json()["detail"]["message"]

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
        assert resp.status_code == 400, (
            f"Expected 400 without any successful run, got {resp.status_code}: {resp.json()}"
        )
        assert "Run binning" in resp.json()["detail"]["message"]

    def test_staleness_and_status_after_param_update(self, client, tmp_dir, larger_german_credit):
        proj_path = tmp_dir / "staleness-regression.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Staleness Test"}).json()
        pid = proj["project_id"]

        plans_resp = client.get(f"/projects/{pid}/plans")
        scorecard = [p for p in plans_resp.json()["plans"] if p["name"] == "Scorecard Pathway"]
        plan_id = scorecard[0]["plan_id"]

        client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(larger_german_credit),
            "dataset_id": "uci-statlog-german-credit",
            "schema_overrides": _GERMAN_COLS_STR,
        })

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

        aw_resp = client.post(f"/plans/{plan_id}/steps/apply-woe/params", json={
            "project_id": pid, "base_plan_version_id": pv_id,
            "params": {"woe_unmatched_policy": "warn"},
        })
        assert aw_resp.status_code == 200
        pv_id = aw_resp.json()["new_plan_version_id"]

        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid, "plan_version_id": pv_id,
        })
        assert run_resp.status_code == 201
        assert run_resp.json()["status"] == "succeeded"

        new_pv_id = store.get_latest_plan_version_id(plan_id)
        params_resp = client.post(f"/plans/{plan_id}/steps/binning/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id,
            "params": {"max_bins": 12},
        })
        assert params_resp.status_code == 200

        plan_resp = client.get(f"/plans/{plan_id}?project_id={pid}")
        assert plan_resp.status_code == 200
        plan_data = plan_resp.json()
        steps_map = {s["step_id"]: s for s in plan_data["steps"]}

        non_stale_upstream = ["import", "define-metadata", "apply-exclusions",
                              "profile", "validate-target", "sample-definition",
                              "split", "explicit-missing-outlier-treatment"]
        for step_id in non_stale_upstream:
            s = steps_map[step_id]
            assert not s["is_stale"], f"{step_id} should not be stale"
            assert s["status"] == "succeeded", (
                f"{step_id} should show 'succeeded' (carried forward), got {s['status']!r}"
            )

        assert steps_map["binning"]["is_stale"]
        stale_downstream = ["initial-woe-iv", "variable-clustering", "variable-selection",
                            "manual-binning", "final-woe-iv", "woe-transform-train",
                            "logistic-regression", "score-scaling", "build-summary-report",
                            "apply-woe", "apply-model",
                            "validation-metrics", "cutoff-analysis", "technical-manifest-stub"]
        for step_id in stale_downstream:
            s = steps_map[step_id]
            assert s["is_stale"], f"{step_id} should be stale (descendant of binning)"
            assert s["status"] == "not_run", (
                f"{step_id} should show 'not_run' (stale), got {s['status']!r}"
            )
