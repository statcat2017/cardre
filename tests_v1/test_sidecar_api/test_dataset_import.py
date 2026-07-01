from __future__ import annotations

import pytest

from cardre.store import ProjectStore

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


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

    def test_import_with_encoding_and_null_values(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()

        csv_path = tmp_dir / "test_latin1.csv"
        csv_path.write_bytes("a,b\n1,N/A\n2,caf\xe9\n".encode("latin-1"))

        resp = client.post("/datasets/import", json={
            "project_id": proj["project_id"],
            "source_path": str(csv_path),
            "encoding": "latin-1",
            "null_values": ["N/A"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["artifact_type"] == "dataset"
        assert data["metadata"]["row_count"] == 2

        store = ProjectStore(proj_path)
        plans = store.get_plans_for_project(proj["project_id"])
        scorecard = [p for p in plans if p["name"] == "Scorecard Pathway"][0]
        plan_id = scorecard["plan_id"]
        pv_id = store.get_latest_plan_version_id(plan_id)
        steps = store.get_plan_version_steps(pv_id)
        import_step = [s for s in steps if s.node_type == "cardre.import_dataset"][0]
        assert import_step.params.get("encoding") == "latin-1"
        assert import_step.params.get("null_values") == ["N/A"]
