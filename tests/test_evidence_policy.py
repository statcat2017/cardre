"""Tests for typed evidence availability results (#215).

The branch-current seam must not swallow infrastructure bugs.
A typed EvidenceCheckResult carries status: current | stale | missing | error.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.services.staleness_service import StalenessExplanation


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
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("step-a", pv_id, "cardre.noop", "1", "transform",
         json.dumps({}), "hash001", "", 0, "step-a"),
    )
    return pv_id


def _seed_current_branch_runs(store):
    """Seed fresh baseline + branch runs so branch-current can short-circuit."""
    pv_id = _seed_minimal_plan(store)
    now = utc_now_iso()
    baseline_run_id = str(uuid.uuid4())
    branch_run_id = str(uuid.uuid4())
    branch_id = "branch-current"

    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (baseline_run_id, pv_id, now, now, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, branch_id, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?, ?)",
        (branch_run_id, pv_id, branch_id, now, now, now),
    )

    for run_id in (baseline_run_id, branch_run_id):
        store.execute(
            "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
            " execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, ?, '[]', '[]')",
            (
                str(uuid.uuid4()),
                run_id,
                "step-a",
                pv_id,
                now,
                now,
                json.dumps({
                    "params_hash": "hash001",
                    "node_type": "cardre.noop",
                    "node_version": "1",
                    "output_artifact_logical_hashes": [],
                }),
            ),
        )

    return pv_id, branch_id, branch_run_id


def test_evidence_check_result_type_exists():
    """EvidenceCheckResult is a typed result with status and diagnostics."""
    from cardre.evidence_locator import EvidenceCheckResult

    result = EvidenceCheckResult(status="missing")
    assert result.status == "missing"
    assert result.run_id is None
    assert result.diagnostics == []

    error_result = EvidenceCheckResult(status="error", diagnostics=[{"code": "DB_ERROR"}])
    assert error_result.status == "error"
    assert error_result.diagnostics == [{"code": "DB_ERROR"}]


def test_missing_evidence_returns_missing(store):
    """A branch check with no prior evidence returns 'missing'."""
    from cardre.evidence_locator import EvidenceLocator

    pv_id = _seed_minimal_plan(store)
    service = EvidenceLocator(store)
    result = service.check_branch_current(pv_id, "nonexistent-branch")
    assert result.status == "missing"
    assert result.run_id is None


def test_current_branch_returns_existing_run(store):
    """A fresh branch with an existing successful run short-circuits."""
    from cardre.evidence_locator import EvidenceLocator

    pv_id, branch_id, branch_run_id = _seed_current_branch_runs(store)
    service = EvidenceLocator(store)
    result = service.check_branch_current(pv_id, branch_id)
    assert result.status == "current"
    assert result.run_id == branch_run_id


def test_stale_branch_does_not_short_circuit(store, monkeypatch):
    """A stale branch must not short-circuit to its existing run."""
    from cardre.evidence_locator import EvidenceLocator
    from cardre.services.staleness_service import StalenessService

    pv_id, branch_id, branch_run_id = _seed_current_branch_runs(store)

    def fake_explain_step(self, plan_version_id, step_id, *, branch_id=None, plan_id=None):
        return StalenessExplanation(
            step_id=step_id,
            status="stale" if branch_id else "fresh",
            upstream_changes={step_id: branch_id == "branch-current"},
            missing_evidence=[],
        )

    monkeypatch.setattr(StalenessService, "explain_step", fake_explain_step)

    service = EvidenceLocator(store)
    result = service.check_branch_current(pv_id, branch_id)
    assert result.status == "stale"
    assert result.run_id is None
    assert branch_run_id != result.run_id


def test_evidence_check_does_not_swallow_db_errors(store, monkeypatch):
    """An unexpected infrastructure error propagates, not silently swallowed (#215)."""
    from cardre.evidence_locator import EvidenceLocator
    from cardre.store.step_repo import StepRepository

    pv_id = _seed_minimal_plan(store)
    service = EvidenceLocator(store)

    def boom(*args, **kwargs):
        raise RuntimeError("DB corruption")

    monkeypatch.setattr(StepRepository, "get_steps", boom)

    # Unexpected exceptions (RuntimeError) propagate as hard failures.
    with pytest.raises(RuntimeError, match="DB corruption"):
        service.check_branch_current(pv_id, "some-branch")


def test_missing_branch_returns_missing(store):
    """A non-existent branch does not fabricate a short-circuit run."""
    from cardre.evidence_locator import EvidenceLocator

    pv_id = _seed_minimal_plan(store)
    service = EvidenceLocator(store)
    result = service.check_branch_current(pv_id, "missing-branch")
    assert result.status == "missing"
