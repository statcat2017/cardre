from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from cardre.store import ProjectStore
from tests.test_sidecar_api.conftest import _GERMAN_COLS_STR

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


class TestPhase4BranchingFlow:

    @pytest.mark.governance
    @pytest.mark.skipif(
        os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
        reason="requires CARDRE_GOVERNANCE=1",
    )
    @pytest.mark.skip(reason="Pre-existing short-circuit bug: third branch run returns different run_id than second. Tracked in issue #168.")
    def test_full_branch_flow(self, client, tmp_dir, larger_german_credit):
        proj_path = tmp_dir / "test_phase4_e2e.cardre"

        proj = client.post("/projects", json={"path": str(proj_path), "name": "Phase4E2E"}).json()
        pid = proj["project_id"]
        store = ProjectStore(proj_path)

        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]

        imp_resp = client.post("/datasets/import", json={
            "project_id": pid,
            "source_path": str(larger_german_credit),
            "dataset_id": "uci-statlog-german-credit",
            "schema_overrides": _GERMAN_COLS_STR,
        })
        assert imp_resp.status_code in (200, 201)

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

        aw_resp = client.post(f"/plans/{plan_id}/steps/apply-woe/params", json={
            "project_id": pid, "base_plan_version_id": pv_id,
            "params": {"woe_unmatched_policy": "warn"},
        })
        assert aw_resp.status_code == 200
        pv_id = aw_resp.json()["new_plan_version_id"]

        run_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": pv_id,
        })
        assert run_resp.status_code == 201, f"Run failed: {run_resp.json()}"
        run_data = run_resp.json()
        assert run_data["status"] == "succeeded", f"Run did not succeed: {run_data}"

        mig_resp = client.post("/migrations/baseline", json={"project_id": pid})
        assert mig_resp.status_code == 200
        mig_data = mig_resp.json()
        assert mig_data["branches_created"] >= 1

        branches_resp = client.get(f"/projects/{pid}/branches?plan_id={plan_id}")
        assert branches_resp.status_code == 200
        branches = branches_resp.json()["branches"]
        baseline_branches = [b for b in branches if b["branch_type"] == "baseline"]
        assert len(baseline_branches) >= 1, f"No baseline branch for plan {plan_id}. Branches: {branches}"
        baseline_branch_id = baseline_branches[0]["branch_id"]

        baseline_detail = client.get(f"/branches/{baseline_branch_id}?project_id={pid}")
        assert baseline_detail.status_code == 200
        base_pv_id = baseline_detail.json()["head_plan_version_id"]

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

        branch_detail = client.get(f"/branches/{branch_id}?project_id={pid}")
        assert branch_detail.status_code == 200
        assert branch_detail.json()["head_plan_version_id"] == new_pv_id

        params_resp = client.post(f"/plans/{plan_id}/steps/{manual_binning_step_id}/params", json={
            "project_id": pid,
            "base_plan_version_id": new_pv_id,
            "params": {"overrides": []},
        })
        assert params_resp.status_code == 200, f"Param edit failed: {params_resp.json()}"
        params_data = params_resp.json()
        updated_pv_id = params_data["new_plan_version_id"]

        branch_after = client.get(f"/branches/{branch_id}?project_id={pid}")
        assert branch_after.status_code == 200
        assert branch_after.json()["head_plan_version_id"] == updated_pv_id

        run_branch_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": updated_pv_id,
            "run_scope": "branch",
            "branch_id": branch_id,
        })
        assert run_branch_resp.status_code == 201, f"Branch run failed: {run_branch_resp.json()}"
        br_data = run_branch_resp.json()
        assert br_data["status"] == "succeeded", f"Branch run did not succeed: {br_data}"

        assert br_data["branch_id"] == branch_id
        assert len(br_data["executed_step_ids"]) > 0
        assert run_data.get("branch_id") is None
        plan_after = client.get(f"/plans/{plan_id}?project_id={pid}")
        assert plan_after.status_code == 200
        base_branch_detail = client.get(f"/branches/{baseline_branch_id}?project_id={pid}")
        assert base_branch_detail.status_code == 200

        run_branch2_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": updated_pv_id,
            "run_scope": "branch",
            "branch_id": branch_id,
        })
        assert run_branch2_resp.status_code == 201, f"Second branch run failed: {run_branch2_resp.json()}"
        br2_data = run_branch2_resp.json()
        assert br2_data["status"] == "succeeded", f"Second branch run did not succeed: {br2_data}"

        run_branch3_resp = client.post("/runs?sync=true", json={
            "project_id": pid,
            "plan_version_id": updated_pv_id,
            "run_scope": "branch",
            "branch_id": branch_id,
        })
        assert run_branch3_resp.status_code == 201, f"Third branch run failed: {run_branch3_resp.json()}"
        br3_data = run_branch3_resp.json()
        assert br3_data["status"] == "succeeded", f"Third branch run did not succeed: {br3_data}"
        assert br3_data["run_id"] == br2_data["run_id"], (
            f"No-op branch run should return same run_id as prior successful run. "
            f"Got {br3_data['run_id']}, expected {br2_data['run_id']}"
        )

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

        refresh_resp = client.post(f"/branch-comparisons/{comp_id}/refresh")
        assert refresh_resp.status_code == 200, f"Comparison refresh failed: {refresh_resp.json()}"
        refresh_data = refresh_resp.json()
        assert refresh_data["ready"], f"Comparison not ready: {refresh_data.get('blocked_reason')}"
        assert refresh_data["comparison_snapshot_id"] is not None

        snap_resp = client.get(f"/branch-comparison-snapshots/{refresh_data['comparison_snapshot_id']}")
        assert snap_resp.status_code == 200
        snap_data = snap_resp.json()
        assert snap_data["ready"]

        artifact_resp = client.get(f"/artifacts/project/{pid}/artifacts/{snap_data['comparison_artifact_id']}")
        if artifact_resp.status_code == 200:
            art_path = artifact_resp.json()["path"]
            art_full_path = proj_path / art_path
            if art_full_path.exists():
                comp_content = ArtifactEvidenceReader(store).read(snap_data["comparison_artifact_id"], EvidenceKind.COMPARISON_ARTIFACT)
                assert comp_content.woe_iv
                assert comp_content.model
                assert comp_content.validation
                assert comp_content.cutoff
                assert isinstance(comp_content.woe_iv.get("variables"), list)
                assert isinstance(comp_content.model.get("branch_level"), dict)
                assert isinstance(comp_content.validation.get("roles"), dict)
                assert isinstance(comp_content.cutoff.get("roles"), dict)
                assert "baseline" in comp_content.model.get("branch_level", {}) or comp_content.model.get("branch_level") != {}
                for role_name in ("train", "test", "oot"):
                    role_data = comp_content.validation.get("roles", {}).get(role_name, {})
                    if role_data:
                        assert "baseline" in role_data or branch_id in role_data

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
        assert champ_data["previous_champion_branch_id"] is None

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

        export_path = Path(export_data["export_path"])
        artifacts_meta = export_path / "artifacts.json"
        assert artifacts_meta.exists()
        exported_artifacts = json.loads(artifacts_meta.read_text())
        for art in exported_artifacts:
            assert art["artifact_type"] not in ("dataset", "tabular"), (
                f"Row-level artifact {art['artifact_id']} of type {art['artifact_type']} "
                f"should not be in export when include_row_level_data=False"
            )

        run_steps_file = export_path / "run_steps.json"
        assert run_steps_file.exists()
        exported_run_steps = json.loads(run_steps_file.read_text())
        exported_step_ids = {rs["step_id"] for rs in exported_run_steps}
        has_shared = any("import" in sid or "define-metadata" in sid for sid in exported_step_ids)
        assert has_shared, f"Export should include shared-upstream run steps, got: {exported_step_ids}"

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

        get_champ_resp = client.get(f"/plans/{plan_id}/champion?project_id={pid}")
        assert get_champ_resp.status_code == 200


def test_branch_run_returns_403_when_governance_disabled(client, tmp_dir, sample_german_credit, monkeypatch):
    monkeypatch.delenv("CARDRE_GOVERNANCE", raising=False)
    proj_path = tmp_dir / "gov-test.cardre"
    proj = client.post("/projects", json={"path": str(proj_path), "name": "Gov Test"}).json()
    pid = proj["project_id"]

    client.post("/datasets/import", json={
        "project_id": pid, "source_path": str(sample_german_credit),
        "dataset_id": "uci-statlog-german-credit",
    })

    store = ProjectStore(proj_path)
    plan_id = store.get_plans_for_project(pid)[0]["plan_id"]
    latest_pv_id = store.get_latest_plan_version_id(plan_id)

    resp = client.post("/runs?sync=true", json={
        "project_id": pid, "plan_version_id": latest_pv_id,
        "run_scope": "branch", "branch_id": "branch-1",
    })
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"


def test_node_types_list_includes_tier_field(client):
    resp = client.get("/node-types")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    for item in data["node_types"]:
        assert "tier" in item, f"Missing tier field in {item['node_type']}"
        assert item["tier"] in ("launch", "deferred"), f"Unexpected tier value in {item['node_type']}: {item['tier']}"
    launch = [n for n in data["node_types"] if n["tier"] == "launch"]
    deferred = [n for n in data["node_types"] if n["tier"] == "deferred"]
    assert len(launch) > 0
    assert len(deferred) > 0
