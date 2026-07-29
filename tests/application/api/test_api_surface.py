"""TestClient coverage for the PR 360 API surface (Commit 4).

Covers runs, plans, node-types, reports, evidence, artifacts, projects and
health against the current create_app/container architecture, using
{project_id} as the authoritative identity (no X-Project-Id/X-Project-Path).
"""

from __future__ import annotations

from tests.application.api.conftest import (
    provision,
    seed_committed_plan,
    seed_run,
)

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_ok(app_env):
    client, _ = app_env
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_openapi_has_no_project_headers(app_env):
    client, _ = app_env
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    raw = spec.text
    assert "X-Project-Id" not in raw, "OpenAPI spec must not contain X-Project-Id header"
    assert "X-Project-Path" not in raw, "OpenAPI spec must not contain X-Project-Path header"


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def test_list_and_get_project(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert any(p["project_id"] == pid for p in resp.json()["projects"])
    resp2 = client.get(f"/projects/{pid}")
    assert resp2.status_code == 200
    assert resp2.json()["project_id"] == pid


def test_get_project_not_found(app_env):
    client, _ = app_env
    resp = client.get("/projects/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


def test_create_project(app_env, tmp_path):
    client, _ = app_env
    resp = client.post("/projects", json={"name": "New", "path": str(tmp_path / "new.cardre")})
    assert resp.status_code == 201
    assert resp.json()["name"] == "New"


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


def test_plan_lifecycle(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.post(f"/projects/{pid}/plans", json={"name": "Plan A"})
    assert resp.status_code == 201
    plan_id = resp.json()["plan_id"]
    resp2 = client.get(f"/projects/{pid}/plans/{plan_id}")
    assert resp2.status_code == 200
    assert resp2.json()["plan_id"] == plan_id
    resp3 = client.get(f"/projects/{pid}/plans")
    assert resp3.status_code == 200
    assert any(p["plan_id"] == plan_id for p in resp3.json()["plans"])


def test_plan_not_found(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/plans/nonexistent")
    assert resp.status_code == 404


def test_plan_version_steps_carry_plan_version_id(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    resp = client.get(f"/projects/{pid}/plan-versions/{pv_id}/steps")
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == 1
    assert steps[0]["plan_version_id"] == pv_id


def test_commit_committed_version_is_conflict(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    resp = client.post(f"/projects/{pid}/plan-versions/{pv_id}/commit")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------


def test_node_types_project_scoped(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/node-types")
    assert resp.status_code == 200
    data = resp.json()
    assert "node_types" in data
    assert any(nt["node_type"] == "cardre.noop" for nt in data["node_types"])


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_run_create_get_list(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    resp = client.post(f"/projects/{pid}/runs", json={"plan_version_id": pv_id, "sync": False})
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["run_id"]
    resp2 = client.get(f"/projects/{pid}/runs/{run_id}")
    assert resp2.status_code == 200
    assert resp2.json()["run_id"] == run_id
    resp3 = client.get(f"/projects/{pid}/runs")
    assert resp3.status_code == 200
    assert any(r["run_id"] == run_id for r in resp3.json()["runs"])


def test_run_response_carries_run_scope_and_force(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    resp = client.post(
        f"/projects/{pid}/runs",
        json={"plan_version_id": pv_id, "sync": False, "force": True},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["run_scope"] == "full_plan"
    assert data["force"] is True


def test_run_not_found(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/runs/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"


def test_run_steps_and_evidence_unknown_run_404(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    assert client.get(f"/projects/{pid}/runs/nonexistent/steps").status_code == 404
    assert client.get(f"/projects/{pid}/runs/nonexistent/evidence").status_code == 404


def test_run_cancel_non_running_409(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    run_id = seed_run(container, pid, pv_id, status="succeeded")
    resp = client.post(f"/projects/{pid}/runs/{run_id}/cancel")
    assert resp.status_code == 409


def test_run_cancel_unknown_404(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.post(f"/projects/{pid}/runs/nonexistent/cancel")
    assert resp.status_code == 404


def test_run_cancel_running_persists_cancel_requested(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    run_id = seed_run(container, pid, pv_id, status="running")
    resp = client.post(f"/projects/{pid}/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["cancel_requested"] is True
    assert resp.json()["status"] == "running"
    # Subsequent GET preserves cancel_requested.
    resp2 = client.get(f"/projects/{pid}/runs/{run_id}")
    assert resp2.json()["cancel_requested"] is True


def test_branch_scope_without_branch_id_rejected(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    resp = client.post(
        f"/projects/{pid}/runs",
        json={"plan_version_id": pv_id, "run_scope": "branch"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Reports / exports
# ---------------------------------------------------------------------------


def test_reports_empty(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/reports")
    assert resp.status_code == 200
    assert resp.json()["reports"] == []


def test_run_reports_unknown_run_404(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/runs/nonexistent/reports")
    assert resp.status_code == 404


def test_exports_empty(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/exports")
    assert resp.status_code == 200
    assert resp.json()["exports"] == []


# ---------------------------------------------------------------------------
# Evidence / artifacts
# ---------------------------------------------------------------------------


def test_artifact_not_found(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/artifacts/nonexistent")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "ARTIFACT_NOT_FOUND"


def test_step_evidence_missing_plan_version_422(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/steps/s1/evidence")
    # plan_version_id is a required query param -> FastAPI validation error.
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Governance routes
# ---------------------------------------------------------------------------


def test_governance_disabled_403(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/governance/branches")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "GOVERNANCE_DISABLED"


def test_governance_list_branches_empty(gov_env, tmp_path):
    client, container = gov_env
    pid, _ = provision(container, tmp_path)
    resp = client.get(f"/projects/{pid}/governance/branches")
    assert resp.status_code == 200
    assert "branches" in resp.json()
