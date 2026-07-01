from __future__ import annotations

from pathlib import Path

import pytest

from cardre.store.schema import STORE_SCHEMA_FAMILY, STORE_SCHEMA_VERSION
from cardre.store import ProjectStore

pytestmark = [pytest.mark.api, pytest.mark.usefixtures("_isolated_registry")]


class TestProjects:
    def test_create_project(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        resp = client.post("/projects", json={"path": str(proj_path), "name": "Test Project"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Project"
        assert data["schema_family"] == STORE_SCHEMA_FAMILY
        assert data["schema_version"] == STORE_SCHEMA_VERSION
        assert (proj_path / "cardre.sqlite").exists()
        for sub in ("datasets", "artifacts", "exports", "logs"):
            assert (proj_path / sub).is_dir()

    def test_create_project_twice(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        resp1 = client.post("/projects", json={"path": str(proj_path), "name": "First"})
        assert resp1.status_code == 201
        resp2 = client.post("/projects", json={"path": str(proj_path), "name": "Second"})
        assert resp2.status_code == 409

    def test_get_project(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        create_resp = client.post("/projects", json={"path": str(proj_path), "name": "My Project"})
        pid = create_resp.json()["project_id"]

        resp = client.get(f"/projects/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Project"
        assert data["path"] == str(proj_path.resolve())
        assert data["schema_family"] == STORE_SCHEMA_FAMILY
        assert data["schema_version"] == STORE_SCHEMA_VERSION

    def test_list_projects_includes_schema_identity(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        client.post("/projects", json={"path": str(proj_path), "name": "Test Project"})

        resp = client.get("/projects")
        assert resp.status_code == 200
        data = resp.json()
        item = data["projects"][0]
        assert item["schema_family"] == STORE_SCHEMA_FAMILY
        assert item["schema_version"] == STORE_SCHEMA_VERSION
        assert item["schema_compatible"] is True
        assert item["schema_error_code"] is None

    def test_list_projects_reports_incompatible_schema_identity(self, client, tmp_dir):
        proj_path = tmp_dir / "test.cardre"
        create_resp = client.post("/projects", json={"path": str(proj_path), "name": "Test Project"})
        pid = create_resp.json()["project_id"]

        store = ProjectStore(proj_path)
        with store.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('schema_family', 'cardre.project_store.v1')"
            )

        resp = client.get("/projects")
        assert resp.status_code == 200
        item = next(p for p in resp.json()["projects"] if p["project_id"] == pid)
        assert item["schema_family"] == "cardre.project_store.v1"
        assert item["schema_compatible"] is False
        assert item["schema_error_code"] == "SCHEMA_VERSION_ERROR"

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
        pid = proj["project_id"]
        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == artifact_id
        assert data["artifact_type"] == "dataset"

    def test_artifact_filters_by_run_id(self, client, tmp_dir, sample_german_credit):
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

        resp = client.get(f"/projects/{pid}/artifacts?run_id={run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["artifacts"]) > 0

    def test_artifact_filters_by_producing_step(self, client, tmp_dir, sample_german_credit):
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

        resp = client.get(f"/projects/{pid}/artifacts?producing_step_id=split")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["artifacts"]) > 0

    def test_json_artifact_summary(self, client, tmp_dir):
        import json as jmod

        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        artifact = store.write_artifact_bytes(
            jmod.dumps({"score": 95, "rank": "A", "details": {"passed": 10, "failed": 0}}).encode(),
            artifact_type="report",
            role="report",
            filename="test.json",
            media_type="application/json",
        )

        resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact.artifact_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary_preview"] is not None
        preview = data["summary_preview"]
        if preview["kind"] == "unknown":
            assert preview["note"]
        else:
            assert preview["fields"]["type"] == "object"
            assert preview["fields"]["key_count"] == 3
            assert preview["fields"]["keys"] == ["score", "rank", "details"]
        assert '"95"' not in jmod.dumps(preview)

    def test_json_artifact_preview(self, client, tmp_dir):
        import json as jmod

        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]

        store = ProjectStore(proj_path)
        artifact = store.write_artifact_bytes(
            jmod.dumps({"alpha": 1, "beta": 2, "gamma": 3}).encode(),
            artifact_type="report",
            role="report",
            filename="test.json",
            media_type="application/json",
        )

        resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact.artifact_id}/preview?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["media_type"] == "application/json"
        assert data["json_content"] is not None
        preview = data["json_content"]
        if preview["kind"] == "unknown":
            assert preview["note"]
        else:
            assert preview["fields"]["type"] == "object"
            assert preview["fields"]["key_count"] == 3
            assert preview["fields"]["keys"] == ["alpha", "beta", "gamma"]
        assert '"1"' not in jmod.dumps(preview)
        assert '"2"' not in jmod.dumps(preview)
        assert '"3"' not in jmod.dumps(preview)

    def test_artifact_preview(self, client, tmp_dir, sample_german_credit):
        proj_path = tmp_dir / "test.cardre"
        proj = client.post("/projects", json={"path": str(proj_path), "name": "Test"}).json()
        pid = proj["project_id"]
        import_resp = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        artifact_id = import_resp.json()["artifact_id"]

        resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}/preview?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == artifact_id
        assert data["media_type"] == "application/vnd.apache.parquet"
        assert isinstance(data["columns"], list)
        assert isinstance(data["rows"], list)

    def test_artifact_preview_uses_store_artifact_path(self, monkeypatch):
        from types import SimpleNamespace

        from sidecar.routes import artifacts as artifacts_route

        calls: list[str] = []

        class FakeStore:
            root = Path("/tmp/unused")

            def get_artifact(self, artifact_id):
                if artifact_id == "art-1":
                    return SimpleNamespace(
                        artifact_id="art-1",
                        artifact_type="report",
                        role="report",
                        path="artifacts/report.parquet",
                        physical_hash="physical",
                        logical_hash="logical",
                        media_type="application/vnd.apache.parquet",
                        created_at="2026-01-01T00:00:00+00:00",
                        metadata={"row_count": 2},
                    )
                return None

            def artifact_path(self, artifact):
                calls.append(artifact.artifact_id)
                return Path("/tmp/explicit-preview.parquet")

        monkeypatch.setattr(artifacts_route, "get_store_for_project", lambda pid: FakeStore())

        def fake_build_parquet_preview(artifact_path, offset, limit, total_rows):
            assert artifact_path == Path("/tmp/explicit-preview.parquet")
            assert offset == 0
            assert limit == 5
            assert total_rows == 2
            return {"total_rows": 2, "columns": [], "rows": []}

        monkeypatch.setattr(artifacts_route, "build_parquet_preview", fake_build_parquet_preview)

        resp = artifacts_route.get_project_artifact_preview("proj-1", "art-1", limit=5, offset=0)

        assert resp.artifact_id == "art-1"
        assert calls == ["art-1"]


class TestProjectScopeIsolation:
    def test_project_run_404_for_wrong_project(self, client, tmp_dir, sample_german_credit):
        proj_a = client.post("/projects", json={
            "path": str(tmp_dir / "a.cardre"), "name": "A",
        }).json()
        pid_a = proj_a["project_id"]
        client.post("/datasets/import", json={
            "project_id": pid_a, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        })
        store_a = ProjectStore(tmp_dir / "a.cardre")
        plan_id = store_a.get_plans_for_project(pid_a)[0]["plan_id"]
        pv_id = store_a.get_latest_plan_version_id(plan_id)
        run_id = client.post("/runs?sync=true", json={
            "project_id": pid_a, "plan_version_id": pv_id,
        }).json()["run_id"]

        pid_b = client.post("/projects", json={
            "path": str(tmp_dir / "b.cardre"), "name": "B",
        }).json()["project_id"]

        for suffix in ("", "/steps", "/manifest"):
            resp = client.get(f"/runs/project/{pid_b}/runs/{run_id}{suffix}")
            assert resp.status_code == 404, f"suffix={suffix}"
            assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND", f"suffix={suffix}"

    def test_project_artifact_metadata_404_for_wrong_project(self, client, tmp_dir, sample_german_credit):
        proj_a = client.post("/projects", json={
            "path": str(tmp_dir / "a.cardre"), "name": "A",
        }).json()
        pid_a = proj_a["project_id"]
        artifact_id = client.post("/datasets/import", json={
            "project_id": pid_a, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        }).json()["artifact_id"]

        pid_b = client.post("/projects", json={
            "path": str(tmp_dir / "b.cardre"), "name": "B",
        }).json()["project_id"]

        resp = client.get(f"/artifacts/project/{pid_b}/artifacts/{artifact_id}")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"

    def test_project_artifact_summary_404_for_wrong_project(self, client, tmp_dir, sample_german_credit):
        proj_a = client.post("/projects", json={
            "path": str(tmp_dir / "a.cardre"), "name": "A",
        }).json()
        pid_a = proj_a["project_id"]
        artifact_id = client.post("/datasets/import", json={
            "project_id": pid_a, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        }).json()["artifact_id"]

        pid_b = client.post("/projects", json={
            "path": str(tmp_dir / "b.cardre"), "name": "B",
        }).json()["project_id"]

        resp = client.get(f"/artifacts/project/{pid_b}/artifacts/{artifact_id}/summary")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"

    def test_project_artifact_preview_404_for_wrong_project(self, client, tmp_dir, sample_german_credit):
        proj_a = client.post("/projects", json={
            "path": str(tmp_dir / "a.cardre"), "name": "A",
        }).json()
        pid_a = proj_a["project_id"]
        artifact_id = client.post("/datasets/import", json={
            "project_id": pid_a, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        }).json()["artifact_id"]

        pid_b = client.post("/projects", json={
            "path": str(tmp_dir / "b.cardre"), "name": "B",
        }).json()["project_id"]

        resp = client.get(f"/artifacts/project/{pid_b}/artifacts/{artifact_id}/preview?limit=5&offset=0")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"

    def test_project_artifact_summary_scoped(self, client, tmp_dir, sample_german_credit):
        proj = client.post("/projects", json={
            "path": str(tmp_dir / "test.cardre"), "name": "Test",
        }).json()
        pid = proj["project_id"]
        artifact_id = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        }).json()["artifact_id"]

        resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == artifact_id
        assert data["artifact_type"] == "dataset"

    def test_project_artifact_preview_scoped(self, client, tmp_dir, sample_german_credit):
        proj = client.post("/projects", json={
            "path": str(tmp_dir / "test.cardre"), "name": "Test",
        }).json()
        pid = proj["project_id"]
        artifact_id = client.post("/datasets/import", json={
            "project_id": pid, "source_path": str(sample_german_credit),
            "dataset_id": "uci-statlog-german-credit",
        }).json()["artifact_id"]

        resp = client.get(f"/artifacts/project/{pid}/artifacts/{artifact_id}/preview?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == artifact_id
        assert data["media_type"] == "application/vnd.apache.parquet"
