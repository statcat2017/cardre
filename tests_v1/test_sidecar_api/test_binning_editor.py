from __future__ import annotations

import pytest

from cardre.store import ProjectStore

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


class TestManualBinningEditor:
    def test_editor_state_requires_run(self, client, tmp_dir, sample_german_credit):
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
        if not data["ready"]:
            assert data["blocked_reason"] is not None

    def test_preview_rejects_wrong_plan_version(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)

        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]

        proof = [p for p in plans if p["name"] == "Proof Pathway"][0]
        proof_pv_id = store.get_latest_plan_version_id(proof["plan_id"])

        resp = client.post(f"/plans/{plan_id}/steps/manual-binning/manual-binning/preview", json={
            "project_id": pid,
            "plan_version_id": proof_pv_id,
            "overrides": [],
        })
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "VERSION_NOT_IN_PLAN"

    def test_preview_validates_override_structure(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(pid)
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)

        resp = client.post(f"/plans/{plan_id}/steps/manual-binning/manual-binning/preview", json={
            "project_id": pid,
            "plan_version_id": pv_id,
            "overrides": "not-a-list",
        })
        assert resp.status_code == 422

    def test_parquet_preview_pagination(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp0 = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}/preview?limit=1&offset=0")
        assert resp0.status_code == 200
        resp1 = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}/preview?limit=1&offset=1")
        assert resp1.status_code == 200

        rows0 = resp0.json()["rows"]
        rows1 = resp1.json()["rows"]
        assert len(rows0) == 1
        assert len(rows1) == 1
        if len(rows0) == 1 and len(rows1) == 1:
            assert rows0 != rows1, "Offset=0 and offset=1 must return different rows"
