"""Tests that RunRepository.create persists all request columns."""
from __future__ import annotations

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry


@pytest.fixture
def provisioned(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test")
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        pv_id = uow.plans.create_version(plan_id, is_committed=True)
        uow.commit()
    registry.register(project_id, root)
    return project_id, pv_id, uow_factory


def test_create_run_persists_request_fields(provisioned):
    """RunRepository.create writes run_scope, branch_id, requested_by, request_id."""
    project_id, pv_id, uow_factory = provisioned
    with uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(
            pv_id,
            run_scope="branch",
            branch_id="br-1",
            requested_by="alice",
            request_id="req-1",
        )
        uow.commit()
        run = uow.runs.get(run_id)
        assert run is not None
        assert run.run_scope == "branch"
        assert run.branch_id == "br-1"
        assert run.started_at
        row = uow._conn.execute(
            "SELECT requested_by, request_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert row["requested_by"] == "alice"
        assert row["request_id"] == "req-1"


def test_create_run_defaults(provisioned):
    """RunRepository.create uses defaults for optional fields."""
    project_id, pv_id, uow_factory = provisioned
    with uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(pv_id)
        uow.commit()
        run = uow.runs.get(run_id)
        assert run is not None
        assert run.run_scope == "full_plan"
        assert run.branch_id is None
        assert run.started_at
        row = uow._conn.execute(
            "SELECT requested_by, request_id, force FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert row["requested_by"] is None
        assert row["request_id"] is None
        assert row["force"] == 0
