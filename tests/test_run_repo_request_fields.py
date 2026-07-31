"""Tests that RunRepo.create persists all request columns."""
from __future__ import annotations


def _seed_committed_plan_version(uow, project_id):
    """Seed a minimal project + plan + committed plan_version. Returns pv_id."""
    plan_id = uow.plans.create_plan(project_id, "Test Plan")
    return uow.plans.create_version(plan_id, [], is_committed=True)


def test_create_run_persists_request_fields(provisioned_project):
    """RunRepo.create writes run_scope, branch_id, requested_by, request_id."""
    project_id, uow_factory, _, _ = provisioned_project

    with uow_factory.for_project(project_id) as uow:
        pv_id = _seed_committed_plan_version(uow, project_id)
        run_id = uow.runs.create(
            pv_id,
            run_scope="branch",
            branch_id="br-1",
            requested_by="alice",
            request_id="req-1",
        )
        run = uow.runs.get(run_id)
        assert run is not None
        assert run.run_scope == "branch"
        assert run.branch_id == "br-1"
        row = uow._conn.execute(
            "SELECT requested_by, request_id, created_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row["requested_by"] == "alice"
        assert row["request_id"] == "req-1"
        assert row["created_at"]


def test_create_run_defaults(provisioned_project):
    """RunRepo.create uses defaults for optional fields."""
    project_id, uow_factory, _, _ = provisioned_project

    with uow_factory.for_project(project_id) as uow:
        pv_id = _seed_committed_plan_version(uow, project_id)
        run_id = uow.runs.create(pv_id)
        run = uow.runs.get(run_id)
        assert run is not None
        assert run.status == "created"
        assert run.run_scope == "full_plan"
        assert run.branch_id is None
        assert run.force is False
        row = uow._conn.execute(
            "SELECT requested_by, request_id, created_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row["requested_by"] is None
        assert row["request_id"] is None
        assert row["created_at"]
