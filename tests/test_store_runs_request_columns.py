"""Tests that the runs table has all required request columns."""
from __future__ import annotations

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry


def test_runs_table_has_request_columns(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "projects" / "project-1"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test")
        uow.commit()
    registry.register(project_id, root)

    with uow_factory.for_project(project_id) as uow:
        cols = {r[1] for r in uow._conn.execute("PRAGMA table_info(runs)").fetchall()}
    required = {
        "run_id", "plan_version_id", "status",
        "run_scope", "force",
        "requested_by", "request_id",
        "created_at", "started_at", "finished_at",
        "heartbeat_at", "active_step_id", "cancel_requested",
    }
    missing = required - cols
    assert not missing, f"runs table missing columns: {sorted(missing)}"
