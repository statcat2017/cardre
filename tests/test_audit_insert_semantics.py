"""Tests for audit table insert semantics (#213).

Audit tables (run_steps, artifacts) must use plain INSERT, not
INSERT OR REPLACE. A duplicate primary key must fail loudly.
"""

from __future__ import annotations

import sqlite3

import pytest

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import RunStep, RunStepStatus


@pytest.fixture
def provisioned(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Test")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, is_committed=True)
        uow.commit()
    registry.register(project_id, root)
    return project_id, pv_id, uow_factory


def test_duplicate_run_step_insert_fails(provisioned):
    """Saving a run_step with an existing run_step_id must fail, not replace (#213)."""
    _, pv_id, uow_factory = provisioned
    now = utc_now_iso()

    with uow_factory.for_project(provisioned[0]) as uow:
        run_id = uow.runs.create(pv_id)
        uow.commit()

    step = RunStep(
        run_step_id="rs-duplicate",
        run_id=run_id,
        step_id="step-a",
        plan_version_id=pv_id,
        status=RunStepStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        execution_fingerprint={},
        warnings=[],
        errors=[],
    )

    with uow_factory.for_project(provisioned[0]) as uow:
        uow.run_steps.insert(step)
        uow.commit()

    with uow_factory.for_project(provisioned[0]) as uow:
        with pytest.raises(sqlite3.IntegrityError):
            uow.run_steps.insert(step)
            uow.commit()
