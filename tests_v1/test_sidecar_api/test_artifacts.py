from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


class TestArtifacts:
    def test_get_artifact(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_type"] == "dataset"

    def test_get_artifact_not_found(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        resp = client.get(f"/artifacts/project/{pid}/artifacts/nonexistent-id")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"
