"""Tests for typed evidence policy results (#215).

The evidence-policy seam must not swallow infrastructure bugs.
A typed EvidenceCheckResult carries status: current | stale | missing | error.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso


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


def test_evidence_check_result_type_exists():
    """EvidenceCheckResult is a typed result with status and diagnostics."""
    from cardre.services.evidence_resolver import EvidenceCheckResult

    result = EvidenceCheckResult(status="missing")
    assert result.status == "missing"
    assert result.run_id is None
    assert result.diagnostics == []

    error_result = EvidenceCheckResult(status="error", diagnostics=[{"code": "DB_ERROR"}])
    assert error_result.status == "error"
    assert error_result.diagnostics == [{"code": "DB_ERROR"}]


def test_missing_evidence_returns_missing(store):
    """A branch check with no prior evidence returns 'missing'."""
    from cardre.services.evidence_resolver import EvidencePolicyService

    pv_id = _seed_minimal_plan(store)
    service = EvidencePolicyService(store)
    result = service.check_branch_current(pv_id, "nonexistent-branch")
    assert result.status == "missing"
    assert result.run_id is None


def test_evidence_check_does_not_swallow_db_errors(store, monkeypatch):
    """An unexpected infrastructure error propagates, not silently swallowed (#215)."""
    from cardre.services.evidence_resolver import EvidencePolicyService
    from cardre.store.step_repo import StepRepository

    pv_id = _seed_minimal_plan(store)
    service = EvidencePolicyService(store)

    def boom(*args, **kwargs):
        raise RuntimeError("DB corruption")

    monkeypatch.setattr(StepRepository, "get_steps", boom)

    # Unexpected exceptions (RuntimeError) propagate as hard failures.
    with pytest.raises(RuntimeError, match="DB corruption"):
        service.check_branch_current(pv_id, "some-branch")
