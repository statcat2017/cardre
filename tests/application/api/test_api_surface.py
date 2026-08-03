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


def test_lifespan_shutdown_drains_async_dispatcher(app_env):
    """The FastAPI lifespan invokes the container's async dispatcher shutdown on
    teardown, so uvicorn shutdown drains outstanding work (P2-2)."""
    client, container = app_env
    dispatcher = getattr(container, "async_dispatcher", None)
    assert dispatcher is not None
    assert dispatcher._shutdown is False, "precondition: not yet shut down"
    with client:
        resp = client.get("/health")
        assert resp.status_code == 200
    # The lifespan teardown ran when the client context exited.
    assert dispatcher._shutdown is True


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


def test_create_canonical_version_populates_steps(app_env, tmp_path):
    import csv

    client, container = app_env
    pid, _ = provision(container, tmp_path)
    plan_resp = client.post(f"/projects/{pid}/plans", json={"name": "P"})
    assert plan_resp.status_code == 201, plan_resp.text
    plan_id = plan_resp.json()["plan_id"]

    csv_path = tmp_path / "in.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["x", "credit_risk_class"])
        w.writeheader()
        w.writerow({"x": 1, "credit_risk_class": "good"})

    resp = client.post(
        f"/projects/{pid}/plans/{plan_id}/canonical-version",
        json={"source_path": str(csv_path)},
    )
    assert resp.status_code == 201, resp.text
    pv = resp.json()
    assert pv["is_committed"] is False

    steps = client.get(f"/projects/{pid}/plan-versions/{pv['plan_version_id']}/steps")
    assert steps.status_code == 200
    assert len(steps.json()) == 31
    assert steps.json()[0]["canonical_step_id"] == "import"


def test_create_canonical_version_unknown_plan_404(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    resp = client.post(
        f"/projects/{pid}/plans/nonexistent/canonical-version",
        json={"source_path": "x.csv"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PLAN_NOT_FOUND"


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


def test_patch_committed_plan_version_returns_409(app_env, tmp_path):
    """A committed plan version is immutable — PATCH must return 409
    PLAN_VERSION_IMMUTABLE (F1)."""
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    resp = client.patch(
        f"/projects/{pid}/plan-versions/{pv_id}",
        json={"description": "Tampered"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "PLAN_VERSION_IMMUTABLE"


def test_patch_draft_plan_version_succeeds(app_env, tmp_path):
    """Draft versions remain editable."""
    from cardre.domain.artifacts import json_logical_hash
    from cardre.domain.step import StepSpec

    client, container = app_env
    pid, _ = provision(container, tmp_path)
    with container.uow_factory.for_project(pid) as uow:
        plan_id = uow.plans.create_plan(pid, "DraftPlan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=False,
        )
        uow.commit()
    resp = client.patch(
        f"/projects/{pid}/plan-versions/{pv_id}",
        json={"description": "Draft update"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Draft update"


def test_patch_draft_step_params_succeeds(app_env, tmp_path):
    from cardre.domain.artifacts import json_logical_hash
    from cardre.domain.step import StepSpec

    client, container = app_env
    pid, _ = provision(container, tmp_path)
    with container.uow_factory.for_project(pid) as uow:
        plan_id = uow.plans.create_plan(pid, "DraftPlan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=False,
        )
        uow.commit()
    resp = client.patch(
        f"/projects/{pid}/plan-versions/{pv_id}/steps/s1",
        json={"params": {"min_iv": 0.05}},
    )
    assert resp.status_code == 200
    steps = client.get(f"/projects/{pid}/plan-versions/{pv_id}/steps").json()
    assert steps[0]["params"] == {"min_iv": 0.05}
    assert steps[0]["params_hash"] == json_logical_hash({"min_iv": 0.05})


def test_patch_committed_step_params_returns_409(app_env, tmp_path):
    client, container = app_env
    pid, _ = provision(container, tmp_path)
    _, pv_id = seed_committed_plan(container, pid)
    resp = client.patch(
        f"/projects/{pid}/plan-versions/{pv_id}/steps/s1",
        json={"params": {"min_iv": 0.05}},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "PLAN_VERSION_IMMUTABLE"


def test_patch_unknown_step_returns_404(app_env, tmp_path):
    from cardre.domain.artifacts import json_logical_hash
    from cardre.domain.step import StepSpec

    client, container = app_env
    pid, _ = provision(container, tmp_path)
    with container.uow_factory.for_project(pid) as uow:
        plan_id = uow.plans.create_plan(pid, "DraftPlan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=False,
        )
        uow.commit()
    resp = client.patch(
        f"/projects/{pid}/plan-versions/{pv_id}/steps/no-such-step",
        json={"params": {}},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "STEP_NOT_FOUND"


def test_patch_null_indeterminate_values_rejected(app_env, tmp_path):
    """The step editor accepts arbitrary JSON params; an explicit null for an
    optional target list must be rejected with a structured 422."""
    import csv
    import json

    from cardre.application.plans.create_canonical_scorecard_version import (
        CreateCanonicalScorecardVersion,
        CreateCanonicalScorecardVersionCommand,
    )
    from cardre.bootstrap.node_catalogue import build_default_catalogue
    from cardre.bootstrap.settings import Settings

    client, container = app_env
    pid, _ = provision(container, tmp_path)
    plan_resp = client.post(f"/projects/{pid}/plans", json={"name": "P"})
    plan_id = plan_resp.json()["plan_id"]
    csv_path = tmp_path / "in.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["x", "outcome"])
        w.writeheader()
        w.writerow({"x": 1, "outcome": "good"})
        w.writerow({"x": 2, "outcome": "bad"})
    cat = build_default_catalogue(Settings())
    create = CreateCanonicalScorecardVersion(
        lambda: container.uow_factory.for_project(pid), cat,
    )
    pv = create(CreateCanonicalScorecardVersionCommand(
        plan_id=plan_id, source_path=str(csv_path), target_column="outcome",
        good_values=["good"], bad_values=["bad"],
    ))
    pv_id = pv.plan_version_id
    steps = client.get(f"/projects/{pid}/plan-versions/{pv_id}/steps").json()
    meta = next(s for s in steps if s["canonical_step_id"] == "define-metadata")

    resp = client.patch(
        f"/projects/{pid}/plan-versions/{pv_id}/steps/{meta['step_id']}",
        json={"params": {**meta["params"], "indeterminate_values": None}},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PARAMETER_VALIDATION_ERROR"
    assert "indeterminate_values must be a list" in json.dumps(resp.json())


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
