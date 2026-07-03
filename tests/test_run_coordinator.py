"""Tests for RunCoordinator — sync/async equivalence, short-circuit, stale recovery.

Tests validate:
- ``run()`` creates and executes runs (sync path)
- ``execute_created_run(run_id)`` recovers request fields from the runs table
- Short-circuit logic for branch and to_node scopes
- Stale-run recovery
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import (
    CardreError,
    PlanVersionNotCommittedError,
    RunScopeNotAvailableForLaunch,
)


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_minimal_plan(store):
    """Seed a plan, plan_version, and steps. Returns pv_id."""
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
    # Insert one step
    store.execute(
        "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
        " params_json, params_hash, branch_label, position, canonical_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("step-a", pv_id, "cardre.noop", "1", "transform",
         json.dumps({}), "hash001", "", 0, "step-a"),
    )
    return pv_id


class TestRunCoordinatorSync:
    """Sync execution path."""

    def test_run_sync_creates_and_executes(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        summary = coordinator.run(pv_id, sync=True)

        assert summary.run_id is not None
        assert summary.plan_version_id == pv_id
        assert summary.status in ("succeeded", "running")
        assert summary.step_count >= 0

    def test_run_sync_returns_with_executed_ids(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        summary = coordinator.run(pv_id, sync=True)

        # Should have step records
        from cardre.store.run_step_repo import RunStepRepository
        rs_repo = RunStepRepository(store)
        steps = rs_repo.get_for_run(summary.run_id)
        assert len(steps) == 1
        assert steps[0].step_id == "step-a"

    def test_plan_not_found_raises(self, tmp_path):
        store = _make_store(tmp_path)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        with pytest.raises(CardreError, match="not found"):
            coordinator.run("nonexistent", sync=True)

    def test_draft_plan_version_is_rejected(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)
        store.execute(
            "UPDATE plan_versions SET is_committed = 0 WHERE plan_version_id = ?",
            (pv_id,),
        )

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        with pytest.raises(PlanVersionNotCommittedError):
            coordinator.run(pv_id, sync=True)


class TestExecuteCreatedRun:
    """execute_created_run recovers request fields from runs table."""

    def test_executes_from_created_run(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        # Manually create a run in the DB
        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id = run_repo.create(pv_id)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        summary = coordinator.execute_created_run(run_id)

        assert summary.run_id == run_id
        assert summary.plan_version_id == pv_id

    def test_execute_nonexistent_run_raises(self, tmp_path):
        store = _make_store(tmp_path)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        with pytest.raises(CardreError, match="not found"):
            coordinator.execute_created_run("nonexistent-run")

    def test_execute_non_running_run_raises(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        # Create a run and mark it as succeeded
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', ?, ?, ?)",
            (run_id, pv_id, utc_now_iso(), utc_now_iso(), utc_now_iso()),
        )

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        with pytest.raises(CardreError, match="not running"):
            coordinator.execute_created_run(run_id)

    def test_recovers_request_fields_from_db(self, tmp_path):
        """requested_by is stored in the real column, not metadata."""
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        # Create a run via RunCoordinator
        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        summary = coordinator.run(pv_id, sync=True, requested_by="test-user")

        # Check that requested_by was stored in the column
        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(summary.run_id)
        assert run is not None
        assert run["requested_by"] == "test-user"

    def test_persists_run_scope_in_column(self, tmp_path):
        """Run scope is persisted in the run_scope column."""
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        summary = coordinator.run(pv_id, sync=True)

        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(summary.run_id)
        assert run is not None
        assert run["run_scope"] == "full_plan"

    def test_to_node_in_column_raises(self, tmp_path):
        """Execute-created-run safety net: to_node in column raises."""
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, target_step_id, "
            " created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?, ?, ?)",
            (run_id, pv_id, "to_node", "step-a", now, now),
        )

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)

        with pytest.raises(RunScopeNotAvailableForLaunch) as exc_info:
            coordinator.execute_created_run(run_id)
        assert exc_info.value.code == "RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH"
        assert exc_info.value.context.get("run_scope") == "to_node"
        assert exc_info.value.context.get("target_step_id") == "step-a"
        from cardre.store.run_repo import RunRepository
        rejected_run = RunRepository(store).get(run_id)
        assert rejected_run is not None
        assert rejected_run["status"] == "failed"
        assert rejected_run["finished_at"] is not None

    def test_to_node_in_column_without_target(self, tmp_path):
        """Safety net also fires for to_node without target_step_id."""
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, "
            " created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?, ?)",
            (run_id, pv_id, "to_node", now, now),
        )

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)

        with pytest.raises(RunScopeNotAvailableForLaunch) as exc_info:
            coordinator.execute_created_run(run_id)
        assert exc_info.value.code == "RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH"
        assert exc_info.value.context.get("run_scope") == "to_node"
        # target_step_id should NOT be present in context
        assert "target_step_id" not in exc_info.value.context
        from cardre.store.run_repo import RunRepository
        rejected_run = RunRepository(store).get(run_id)
        assert rejected_run is not None
        assert rejected_run["status"] == "failed"
        assert rejected_run["finished_at"] is not None

    def test_execute_created_run_reads_column_not_metadata(self, tmp_path):
        """execute_created_run reads run_scope from real column, not metadata decoy.

        Current code reads ``metadata.get('run_scope')`` which is 'full_plan'
        (decoy), so no exception.  Fixed code reads the column which is
        'to_node' -> raises RunScopeNotAvailableForLaunch.
        """
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        # Column run_scope='to_node' but metadata decoy says 'full_plan'.
        run_id = str(uuid.uuid4())
        now = utc_now_iso()
        metadata_json = json.dumps({"run_scope": "full_plan"})
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, target_step_id, "
            " created_at, started_at, metadata_json) "
            "VALUES (?, ?, 'running', ?, ?, ?, ?, ?)",
            (run_id, pv_id, "to_node", "step-a", now, now, metadata_json),
        )

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)

        # Current code reads metadata -> no error (WRONG).
        # After fix reads column 'to_node' -> raises RunScopeNotAvailableForLaunch.
        with pytest.raises(RunScopeNotAvailableForLaunch) as exc_info:
            coordinator.execute_created_run(run_id)
        assert exc_info.value.context.get("target_step_id") == "step-a"



class TestShortCircuit:
    """Short-circuit logic for branch and to_node scopes."""

    def test_to_node_short_circuit(self, tmp_path):
        """A to_node run is rejected early with RunScopeNotAvailableForLaunch."""
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)

        with pytest.raises(RunScopeNotAvailableForLaunch) as exc_info:
            coordinator.run(
                pv_id, run_scope="to_node", target_step_id="step-a", sync=True,
            )
        assert exc_info.value.code == "RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH"
        assert exc_info.value.context.get("run_scope") == "to_node"
        assert exc_info.value.context.get("target_step_id") == "step-a"


class TestStaleRecovery:
    """Stale-run recovery logic."""

    def test_recovery_of_stale_run(self, tmp_path):
        """A run with an old heartbeat should be recovered."""
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        # Create a "stale" run with a very old heartbeat
        old_time = "2020-01-01T00:00:00"
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, heartbeat_at) "
            "VALUES (?, ?, 'running', ?, ?, ?)",
            (run_id, pv_id, old_time, old_time, old_time),
        )

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        # Running a new plan should recover the stale run
        summary = coordinator.run(pv_id, sync=True)
        assert summary.run_id is not None

        # The stale run should have been interrupted
        from cardre.store.run_repo import RunRepository
        stale_run = RunRepository(store).get(run_id)
        assert stale_run["status"] == "interrupted"


class TestAsyncDispatch:
    """Async dispatch creates run and dispatches to background thread."""

    def test_async_returns_immediately(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        summary = coordinator.run(pv_id, sync=False)

        assert summary.run_id is not None
        # The async dispatch starts a thread but doesn't wait for it
        # The run should be in "running" state
        assert summary.status == "running"


class TestRunSummary:
    """RunSummary structure."""

    def test_summary_fields(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        from cardre.services.run_coordinator import RunCoordinator
        coordinator = RunCoordinator(store)
        summary = coordinator.run(pv_id, sync=True)

        assert isinstance(summary.run_id, str)
        assert isinstance(summary.plan_version_id, str)
        assert isinstance(summary.status, str)
        assert isinstance(summary.started_at, str)
        assert isinstance(summary.step_count, int)
        assert isinstance(summary.executed_step_ids, list)

    def test_failed_step_marks_run_failed(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path)
        pv_id = _seed_minimal_plan(store)

        from cardre.domain.run import RunStepStatus
        from cardre.execution.executor import PlanExecutor
        from cardre.services.run_coordinator import RunCoordinator

        def fake_run_plan_version(self, plan_version_id, run_id, *, force=False, branch_id=None, precomputed_outputs=None, precomputed_records=None):
            now = utc_now_iso()
            store.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '[]', '[]')",
                ("rs-failed", run_id, "step-a", plan_version_id, RunStepStatus.FAILED.value, now, now),
            )
            return run_id

        monkeypatch.setattr(PlanExecutor, "run_plan_version", fake_run_plan_version)

        coordinator = RunCoordinator(store)
        summary = coordinator.run(pv_id, sync=True)

        assert summary.status == "failed"

        assert isinstance(summary.run_id, str)
        assert isinstance(summary.plan_version_id, str)
        assert isinstance(summary.status, str)
        assert isinstance(summary.started_at, str)
        assert isinstance(summary.step_count, int)
        assert isinstance(summary.executed_step_ids, list)
