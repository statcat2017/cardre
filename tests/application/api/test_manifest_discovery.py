"""F10 — finalized-run manifest must be retrievable through the API.

After a normal completed run, the canonical manifest is written to
``manifests/runs/{run_id}.json`` but no HTTP route exposes it —
``/reports`` and ``/exports`` only list DB-registered rows that FinalizeRun
never writes. This test pins the new ``GET /runs/{run_id}/manifest`` surface.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.api.app import create_app
from cardre.bootstrap.container import build_container
from cardre.bootstrap.settings import Settings
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.step import StepSpec


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))
    monkeypatch.setenv("CARDRE_ALLOW_RAW_PROJECT_PATH", "1")
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    return TestClient(app), container


def _provision(container, tmp_path):
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "p.cardre"
    provisioner.initialize(root)
    with container.uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("P")
        uow.commit()
    container.project_registry.register(project_id, root)
    return project_id, root


def _seed_finalized_run(container, project_id):
    """Seed a committed plan + succeeded run and finalize it so a canonical
    manifest is published."""
    from cardre.domain.run import RunStatus

    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    container.finalize_run(project_id)(run_id, "succeeded", worker_generation=0)
    return plan_id, pv_id, run_id


def test_run_manifest_retrievable_via_api(env, tmp_path):
    """GET /runs/{run_id}/manifest returns the canonical manifest JSON for a
    finalized run (F10)."""
    client, container = env
    project_id, root = _provision(container, tmp_path)
    _, _, run_id = _seed_finalized_run(container, project_id)

    resp = client.get(f"/projects/{project_id}/runs/{run_id}/manifest")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["status"] == "succeeded"
    assert data["manifest_hash"], "manifest must carry its self-hash"

    # It must match what is on disk.
    import json

    disk = json.loads((root / "manifests" / "runs" / f"{run_id}.json").read_text())
    assert disk["manifest_hash"] == data["manifest_hash"]


def test_run_manifest_unknown_run_404(env, tmp_path):
    client, container = env
    project_id, _ = _provision(container, tmp_path)
    resp = client.get(f"/projects/{project_id}/runs/nonexistent/manifest")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "RUN_NOT_FOUND"


def test_finalized_manifest_appears_in_reports_listing(env, tmp_path):
    """The canonical manifest of a finalized run must appear in GET /reports —
    the pre-rewrite behaviour the /reports endpoints provided (F10)."""
    client, container = env
    project_id, _ = _provision(container, tmp_path)
    _, _, run_id = _seed_finalized_run(container, project_id)

    resp = client.get(f"/projects/{project_id}/reports")
    assert resp.status_code == 200, resp.text
    reports = resp.json()["reports"]
    assert any(r["run_id"] == run_id and r["report_type"] == "manifest" for r in reports), (
        f"reports listing missing manifest for run {run_id}: {reports}"
    )
    manifest = next(r for r in reports if r["report_type"] == "manifest")
    assert manifest["created_at"], (
        f"manifest entry must carry the run's finished_at, got empty: {manifest}"
    )

    # Run-scoped listing includes it too.
    resp_run = client.get(f"/projects/{project_id}/runs/{run_id}/reports")
    assert resp_run.status_code == 200, resp_run.text
    run_reports = resp_run.json()["reports"]
    assert any(r["run_id"] == run_id and r["report_type"] == "manifest" for r in run_reports)


def test_reports_empty_when_no_manifest(env, tmp_path):
    """A project with no finalized runs (no manifests) still lists empty."""
    client, container = env
    project_id, _ = _provision(container, tmp_path)
    resp = client.get(f"/projects/{project_id}/reports")
    assert resp.status_code == 200
    assert resp.json()["reports"] == []


def test_run_manifest_missing_manifest_404(env, tmp_path):
    """A run with no published manifest (e.g. a failed seed) returns 404."""
    client, container = env
    project_id, root = _provision(container, tmp_path)
    from cardre.domain.run import RunStatus

    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.FAILED, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()

    resp = client.get(f"/projects/{project_id}/runs/{run_id}/manifest")
    assert resp.status_code == 404
