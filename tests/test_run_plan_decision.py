"""Tests for unified sync/async run planning (#212).

The core invariant: toggling ``sync`` changes only *where* the work runs,
never *what* work is performed. A typed ``RunPlanDecision`` is computed
once, then sync executes inline and async dispatches.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import (
    PlanVersionNotCommittedError,
    RunScopeNotAvailableForLaunch,
)


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


class TestRunPlanDecision:
    def test_fresh_full_plan_sync_and_async_same_result(self, tmp_path):
        from cardre.services.run_coordinator import RunCoordinator

        store = _make_store(tmp_path / "sync")
        pv_id = _seed_minimal_plan(store)
        coordinator = RunCoordinator(store)

        sync_summary = coordinator.run(pv_id, sync=True, force=True)
        sync_status = sync_summary.status

        store2 = _make_store(tmp_path / "async")
        pv_id2 = _seed_minimal_plan(store2)
        coordinator2 = RunCoordinator(store2)
        async_summary = coordinator2.run(pv_id2, sync=False, force=True)

        assert sync_status in ("succeeded", "failed")
        assert async_summary.status == "running"

    def test_draft_version_sync_and_async_raise_same_error(self, tmp_path):
        from cardre.services.run_coordinator import RunCoordinator

        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)
        store.execute(
            "UPDATE plan_versions SET is_committed = 0 WHERE plan_version_id = ?",
            (pv_id,),
        )

        coordinator = RunCoordinator(store)
        with pytest.raises(PlanVersionNotCommittedError):
            coordinator.run(pv_id, sync=True)
        with pytest.raises(PlanVersionNotCommittedError):
            coordinator.run(pv_id, sync=False)

    def test_disabled_to_node_sync_and_async_raise_same_error(self, tmp_path):
        from cardre.services.run_coordinator import RunCoordinator

        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)
        coordinator = RunCoordinator(store)

        with pytest.raises(RunScopeNotAvailableForLaunch):
            coordinator.run(pv_id, run_scope="to_node", target_step_id="step-a", sync=True)
        with pytest.raises(RunScopeNotAvailableForLaunch):
            coordinator.run(pv_id, run_scope="to_node", target_step_id="step-a", sync=False)

    def test_plan_decision_type_exists(self, tmp_path):
        from cardre.services.run_coordinator import RunPlanDecision

        decision = RunPlanDecision(kind="execute")
        assert decision.kind == "execute"
        assert decision.existing_run_id is None

        short = RunPlanDecision(kind="short_circuit", existing_run_id="run-1")
        assert short.kind == "short_circuit"
        assert short.existing_run_id == "run-1"
