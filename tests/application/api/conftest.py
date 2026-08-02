"""Shared TestClient fixtures for the PR 360 API surface (Commit 4).

Each test builds a fresh app via ``create_app(build_container(Settings))`` so
the per-test ``CARDRE_REGISTRY_PATH`` is honoured, and ``{project_id}`` is the
authoritative project identity (resolved through the registry). No
``X-Project-Id``/``X-Project-Path`` headers are used.
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
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    return TestClient(app), container


@pytest.fixture
def gov_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDRE_GOVERNANCE", "1")
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))
    settings = Settings.from_env()
    container = build_container(settings)
    app = create_app(container)
    return TestClient(app), container


def provision(container, tmp_path, name="Proj"):
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / f"{name}.cardre"
    provisioner.initialize(root)
    with container.uow_factory.for_root(root) as uow:
        project_id = uow.projects.create(name)
        uow.commit()
    container.project_registry.register(project_id, root)
    return project_id, root


def seed_committed_plan(container, project_id, steps=None):
    if steps is None:
        steps = [StepSpec(
            step_id="s1", node_type="cardre.noop", node_version="1",
            category="transform", params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
        )]
    with container.uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, steps, is_committed=True)
        uow.commit()
    return plan_id, pv_id


def seed_run(container, project_id, pv_id, status="succeeded"):
    from cardre.domain.run import RunStatus
    with container.uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(pv_id)
        if status == "succeeded":
            uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
            uow.runs.transition(run_id, RunStatus.SUCCEEDED)
        elif status == "running":
            uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
            uow.runs.heartbeat(run_id)
        uow.commit()
    return run_id
