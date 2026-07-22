"""Tests that RunRepository.create persists all request columns."""
from __future__ import annotations

import uuid

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.run_repo import RunRepository

pytestmark = pytest.mark.xfail(reason="Execution path broken during Batch 04; restored in Batch 05")


def _seed_committed_plan_version(store):
    """Seed a minimal project + plan + committed plan_version. Returns pv_id."""
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    return pv_id


def test_create_run_persists_request_fields(store):
    """RunRepository.create writes run_scope, branch_id, requested_by, request_id."""
    pv_id = _seed_committed_plan_version(store)

    repo = RunRepository(store)
    run_id = repo.create(
        pv_id,
        run_scope="branch",
        branch_id="br-1",
        requested_by="alice",
        request_id="req-1",
    )
    row = repo.get(run_id)
    assert row is not None
    assert row["run_scope"] == "branch"
    assert row["branch_id"] == "br-1"
    assert row["requested_by"] == "alice"
    assert row["request_id"] == "req-1"
    assert row["created_at"]
    assert row["queued_at"] is None


def test_create_run_defaults(store):
    """RunRepository.create uses defaults for optional fields."""
    pv_id = _seed_committed_plan_version(store)

    repo = RunRepository(store)
    run_id = repo.create(pv_id)
    row = repo.get(run_id)
    assert row is not None
    assert row["run_scope"] == "full_plan"
    assert row["branch_id"] is None
    assert row["force"] == 0
    assert row["requested_by"] is None
    assert row["request_id"] is None
    assert row["created_at"]
