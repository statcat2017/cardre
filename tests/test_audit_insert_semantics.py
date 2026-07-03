"""Tests for audit table insert semantics (#213).

Audit tables (run_steps, artifacts) must use plain INSERT, not
INSERT OR REPLACE. A duplicate primary key must fail loudly.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import RunStep, RunStepStatus


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_minimal_plan(store):
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    return pv_id


def test_duplicate_run_step_insert_fails(tmp_path):
    """Saving a run_step with an existing run_step_id must fail, not replace (#213)."""
    from cardre.store.run_step_repo import RunStepRepository

    store = _make_store(tmp_path)
    pv_id = _seed_minimal_plan(store)

    run_id = str(uuid.uuid4())
    now = utc_now_iso()
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) "
        "VALUES (?, ?, 'running', ?, ?)",
        (run_id, pv_id, now, now),
    )

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

    repo = RunStepRepository(store)
    repo.save(step)

    with pytest.raises(Exception):
        repo.save(step)
