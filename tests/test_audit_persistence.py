"""Tests for honest audit persistence (#213).

A step-recording failure must raise a typed error, not fabricate an
in-memory RunStep. The run must be marked failed with a diagnostic.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso

pytestmark = pytest.mark.xfail(reason="Old StepRunner/execution path; needs NodeContext update")


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


def test_step_recording_failure_raises_not_fabricated(tmp_path, monkeypatch):
    """_record_run_step failure must raise, not return a phantom RunStep (#213)."""
    from cardre.domain.errors import CardreError
    from cardre.execution.executor import PlanExecutor

    store = _make_store(tmp_path)
    pv_id = _seed_minimal_plan(store)

    executor = PlanExecutor(store)

    def failing_record(self, *args, **kwargs):
        raise RuntimeError("DB write failed")

    monkeypatch.setattr(PlanExecutor, "_record_run_step_from_result", failing_record)

    with pytest.raises(CardreError) as exc_info:
        executor.run_plan_version(pv_id, "run-1", force=True)
    assert exc_info.value.code == "STEP_RECORDING_FAILED"


def test_assert_run_audit_integrity_helper_exists():
    """The integrity helper is importable and callable."""
    from cardre.execution.run_lifecycle import assert_run_audit_integrity
    assert callable(assert_run_audit_integrity)


def test_fallback_fingerprint_clears_output_hashes(tmp_path, monkeypatch):
    """When a successful execution's recording fails and the fallback
    retry succeeds, the persisted failed step has empty
    output_artifact_logical_hashes and no node_metrics."""
    from cardre.domain.run import RunStepStatus
    from cardre.execution.executor import PlanExecutor

    store = _make_store(tmp_path)
    pv_id = _seed_minimal_plan(store)

    executor = PlanExecutor(store)
    original_record = PlanExecutor._record_run_step_from_result

    call_count = 0

    def _controlled_record(self, run_id, spec, plan_version_id, result, *, run_branch_id=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("First write fails")
        return original_record(self, run_id, spec, plan_version_id, result, run_branch_id=run_branch_id)

    monkeypatch.setattr(
        PlanExecutor, "_record_run_step_from_result", _controlled_record,
    )

    # The step will succeed (noop), then the first record call fails,
    # the fallback retry succeeds.  The persisted failed step should
    # have empty output_artifact_logical_hashes.
    from cardre.store.run_repo import RunRepository
    from cardre.store.run_step_repo import RunStepRepository

    run_id = RunRepository(store).create(pv_id)
    executor.run_plan_version(pv_id, run_id, force=True)

    steps = RunStepRepository(store).get_for_run(run_id)
    assert len(steps) == 1
    rs = steps[0]
    assert rs.status == RunStepStatus.FAILED
    fp = rs.execution_fingerprint
    assert fp.get("output_artifact_logical_hashes") == [], (
        f"Expected empty output hashes, got {fp.get('output_artifact_logical_hashes')}"
    )
    assert "node_metrics" not in fp, (
        "node_metrics should be absent from the fallback fingerprint"
    )
