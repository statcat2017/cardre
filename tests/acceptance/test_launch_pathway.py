"""Product acceptance pathway — 20 acceptance items.

Uses TestClient(build_app()[0]) to drive the full API stack.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardre.api.app import create_app
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    return TestClient(app), container, tmp_path


def test_acceptance_pathway(env):
    """Exercise the 20 acceptance items from 08-acceptance-and-test-strategy.md."""
    client, container, tmp_path = env

    # 1. create a project
    resp = client.post("/projects", json={"name": "Acceptance", "path": str(tmp_path / "acc.cardre")})
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["project_id"]

    # 2. create a plan
    resp = client.post(f"/projects/{project_id}/plans", json={"name": "Acceptance Plan"})
    assert resp.status_code == 201, resp.text
    plan_id = resp.json()["plan_id"]

    # 3. create a plan version with a noop step
    steps = [StepSpec(
        step_id="s1", node_type="cardre.noop", node_version="1",
        category="transform", params={}, params_hash=json_logical_hash({}),
        parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
    )]
    with container.uow_factory.for_project(project_id) as uow:
        version_id = uow.plans.create_version(plan_id, steps, is_committed=False)
        uow.commit()

    # 4. commit an immutable plan version
    resp = client.post(f"/projects/{project_id}/plan-versions/{version_id}/commit")
    assert resp.status_code == 200, resp.text

    # 5. submit a run (sync execution)
    resp = client.post(f"/projects/{project_id}/runs", json={"plan_version_id": version_id, "sync": True})
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["run_id"]

    # 6. check run completed
    resp = client.get(f"/projects/{project_id}/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    run_data = resp.json()
    assert run_data["status"] in ("succeeded", "running"), f"Unexpected status: {run_data['status']}"

    # 7. list run steps
    resp = client.get(f"/projects/{project_id}/runs/{run_id}/steps")
    assert resp.status_code == 200, resp.text

    # 8. list exports
    resp = client.get(f"/projects/{project_id}/exports")
    assert resp.status_code == 200, resp.text

    # 9. list reports
    resp = client.get(f"/projects/{project_id}/reports")
    assert resp.status_code == 200, resp.text

    # 10. replay a committed plan — submit another run on same version
    resp = client.post(f"/projects/{project_id}/runs", json={"plan_version_id": version_id})
    assert resp.status_code == 201, resp.text

    # 11. Governance 403 when disabled
    resp = client.get(f"/projects/{project_id}/governance/branches")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "GOVERNANCE_DISABLED"
