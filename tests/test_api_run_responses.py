from __future__ import annotations

import json
import uuid
from pathlib import Path

from cardre.domain.diagnostics import utc_now_iso


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _write_input_csv(project_root: Path) -> Path:
    input_path = project_root / "input.csv"
    input_path.write_text("credit_amount,age_years,credit_risk_class\n1000,35,good\n2500,42,bad\n", encoding="utf-8")
    return input_path


def _seed_plan_version(store, input_path: Path):
    from cardre.config import CardreConfig
    from cardre.services.project_resolver import ProjectResolver
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )
    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    resolver.register_project(project_id, store.root)
    for sid, ntype, params, pos in [
        ("step-import", "cardre.import_dataset", {"source_path": str(input_path)}, 0),
        ("step-profile", "cardre.profile_dataset", {}, 1),
        ("step-export", "cardre.technical_manifest_export", {}, 2),
    ]:
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, pv_id, ntype, "1", "transform", json.dumps(params), f"hash-{sid}", "", pos, sid),
        )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, 0)",
        (pv_id, "step-import", "step-profile"),
    )
    store.execute(
        "INSERT INTO plan_step_edges (plan_version_id, parent_step_id, child_step_id, edge_order) "
        "VALUES (?, ?, ?, 0)",
        (pv_id, "step-profile", "step-export"),
    )
    return project_id, pv_id


class TestRunResponseContracts:
    RUN_FIELDS = {"run_id", "plan_version_id", "status", "started_at", "finished_at",
                  "step_count", "branch_id", "executed_step_ids", "diagnostics",
                  "latest_error", "heartbeat_at", "is_stale"}
    STEP_FIELDS = {"run_step_id", "run_id", "step_id", "plan_version_id", "status",
                   "started_at", "finished_at", "execution_fingerprint", "warnings", "errors"}

    def test_create_run_response_fields(self, api_client, tmp_path):
        tmp = tmp_path / "create-run-resp"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id = _seed_plan_version(store, input_path)
        store.close()
        resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert set(data.keys()) == self.RUN_FIELDS
        assert data["status"] == "succeeded"
        assert isinstance(data["step_count"], int)
        assert isinstance(data["executed_step_ids"], list)
        assert isinstance(data["diagnostics"], list)

    def test_get_run_response_fields(self, api_client, tmp_path):
        tmp = tmp_path / "get-run-resp"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id = _seed_plan_version(store, input_path)
        store.close()
        create_resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        run_id = create_resp.json()["run_id"]
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == self.RUN_FIELDS
        assert data["run_id"] == run_id
        assert data["plan_version_id"] == pv_id

    def test_list_runs_response_shape(self, api_client, tmp_path):
        tmp = tmp_path / "list-runs-resp"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id = _seed_plan_version(store, input_path)
        store.close()
        api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        resp = api_client.get(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert isinstance(data["runs"], list)
        if data["runs"]:
            run = data["runs"][0]
            assert "run_id" in run
            assert "plan_version_id" in run
            assert "status" in run
            assert "started_at" in run

    def test_run_steps_response_fields(self, api_client, tmp_path):
        tmp = tmp_path / "steps-resp"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id = _seed_plan_version(store, input_path)
        store.close()
        create_resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        run_id = create_resp.json()["run_id"]
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/steps",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        steps = resp.json()
        assert isinstance(steps, list)
        if steps:
            step = steps[0]
            assert set(step.keys()) == self.STEP_FIELDS

    def test_run_evidence_response_fields(self, api_client, tmp_path):
        tmp = tmp_path / "evidence-resp"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id = _seed_plan_version(store, input_path)
        store.close()
        create_resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        run_id = create_resp.json()["run_id"]
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        edges = resp.json()
        assert isinstance(edges, list)
        if edges:
            edge = edges[0]
            EXPECTED_EVIDENCE_FIELDS = {
                "evidence_edge_id", "run_id", "run_step_id", "plan_version_id",
                "step_id", "parent_step_id", "source_run_id", "source_run_step_id",
                "policy", "source_label", "is_reused", "is_stale",
                "stale_reason", "created_at", "artifacts",
            }
            assert set(edge.keys()) == EXPECTED_EVIDENCE_FIELDS
            assert isinstance(edge["artifacts"], list)
            if edge["artifacts"]:
                art = edge["artifacts"][0]
                EXPECTED_ARTIFACT_FIELDS = {
                    "evidence_artifact_id", "evidence_edge_id", "artifact_id",
                    "role", "created_at",
                }
                assert set(art.keys()) == EXPECTED_ARTIFACT_FIELDS

    def test_get_run_with_diagnostics(self, api_client, tmp_path):
        tmp = tmp_path / "diag-resp"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id = _seed_plan_version(store, input_path)
        store.close()
        create_resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        run_id = create_resp.json()["run_id"]
        from cardre.store.db import ProjectStore
        ro_store = ProjectStore(tmp / "test.cardre")
        ro_store.open()
        ro_store.execute(
            "INSERT INTO diagnostics (diagnostic_id, run_id, code, message, severity, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, "TEST_DIAG", "Test diagnostic", "error", utc_now_iso()),
        )
        ro_store.close()
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["diagnostics"]) > 0
        diag = data["diagnostics"][0]
        assert "code" in diag
        assert "message" in diag
        assert "severity" in diag

    def test_get_run_404_envelope(self, api_client, tmp_path):
        store = _make_store(tmp_path)
        project_id = str(uuid.uuid4())
        from cardre.config import CardreConfig
        from cardre.services.project_resolver import ProjectResolver
        resolver = ProjectResolver(CardreConfig.from_env().registry_path)
        resolver.register_project(project_id, store.root)
        store.close()
        resp = api_client.get(
            f"/projects/{project_id}/runs/nonexistent",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "RUN_NOT_FOUND"
        assert "message" in data["detail"]
        assert "context" in data["detail"]

    def test_post_run_wrong_project_404(self, api_client, tmp_path):
        store = _make_store(tmp_path)
        project_id = str(uuid.uuid4())
        from cardre.config import CardreConfig
        from cardre.services.project_resolver import ProjectResolver
        resolver = ProjectResolver(CardreConfig.from_env().registry_path)
        resolver.register_project(project_id, store.root)
        store.close()
        resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": "nonexistent-pv", "sync": True},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "PLAN_VERSION_NOT_FOUND"

    def test_list_run_evidence_with_artifacts(self, api_client, tmp_path):
        tmp = tmp_path / "ev-with-art"
        store = _make_store(tmp)
        input_path = _write_input_csv(tmp)
        project_id, pv_id = _seed_plan_version(store, input_path)
        store.close()
        create_resp = api_client.post(
            f"/projects/{project_id}/runs",
            headers={"X-Project-Id": project_id},
            json={"plan_version_id": pv_id, "sync": True, "force": True},
        )
        run_id = create_resp.json()["run_id"]
        resp = api_client.get(
            f"/projects/{project_id}/runs/{run_id}/evidence",
            headers={"X-Project-Id": project_id},
        )
        assert resp.status_code == 200
        edges = resp.json()
        for edge in edges:
            assert isinstance(edge["is_reused"], bool)
            assert isinstance(edge["is_stale"], bool)
