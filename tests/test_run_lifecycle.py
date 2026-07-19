"""Tests for RunLifecycle — lease, finalise, manifest writing."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from cardre.domain.diagnostics import utc_now_iso
from cardre.execution.run_lifecycle import (
    RunFinalisation,
    RunLifecycle,
    build_manifest_payload,
    finalise_run,
)


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_simple_run(store):
    """Create a minimal run with a plan version."""
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
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
        (run_id, pv_id, now, now),
    )
    return store, pv_id, run_id


class TestRunLifecycle:
    """RunLifecycle.start, finalise, context manager."""

    def test_start_creates_run(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = str(uuid.uuid4())
        project_id = str(uuid.uuid4())
        plan_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )

        from cardre.store.run_repo import RunRepository
        run_id = RunRepository(store).create(pv_id)
        lifecycle = RunLifecycle.start(store, pv_id, run_id=run_id)
        assert lifecycle.run_id == run_id
        assert lifecycle.plan_version_id == pv_id

        run = RunRepository(store).get(lifecycle.run_id)
        assert run is not None
        assert run["status"] == "running"

    def test_finalise_succeeded(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        lifecycle = RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="full_plan",
        )
        lifecycle.finalise("succeeded")

        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(run_id)
        assert run["status"] == "succeeded"
        assert run["finished_at"] is not None

    def test_finalise_cancelled(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        lifecycle = RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="to_node",
        )
        lifecycle.finalise("cancelled")

        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(run_id)
        assert run["status"] == "cancelled"

    def test_context_manager_finalises_on_exit(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        with RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="full_plan",
        ) as lifecycle:
            lifecycle.finalise("succeeded")

        # Verify finalised
        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(run_id)
        assert run["status"] == "succeeded"

    def test_context_manager_finalises_failed_on_exception(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        try:
            with RunLifecycle(
                store=store, run_id=run_id, plan_version_id=pv_id,
                execution_mode="full_plan",
            ):
                raise ValueError("something went wrong")
        except ValueError:
            pass

        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(run_id)
        assert run["status"] == "failed"

    def test_double_finalise_is_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        lifecycle = RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="full_plan",
        )
        lifecycle.finalise("succeeded")
        lifecycle.finalise("succeeded")  # should not raise

        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(run_id)
        assert run["status"] == "succeeded"

    def test_manifest_written(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        with RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="full_plan",
        ) as lifecycle:
            lifecycle.finalise("succeeded")

        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "succeeded"
        assert manifest["execution_mode"] == "full_plan"
        assert "steps" in manifest

    def test_lease_creates_unique_runs(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id = str(uuid.uuid4())
        project_id = str(uuid.uuid4())
        plan_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )

        from cardre.store.run_repo import RunRepository
        run_repo = RunRepository(store)
        run_id1 = run_repo.create(pv_id)
        run_id2 = run_repo.create(pv_id)
        lc1 = RunLifecycle.start(store, pv_id, run_id=run_id1)
        lc2 = RunLifecycle.start(store, pv_id, run_id=run_id2, force=True)
        assert lc1.run_id != lc2.run_id


class TestFinaliseRun:
    """Standalone finalise_run function."""

    def test_writes_manifest_and_updates_status(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        finalise_run(store, RunFinalisation(
            run_id=run_id,
            plan_version_id=pv_id,
            status="succeeded",
            execution_mode="full_plan",
            finished_at=utc_now_iso(),
        ))

        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(run_id)
        assert run["status"] == "succeeded"

        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists()


class TestBuildManifestPayload:
    """build_manifest_payload produces correct structure."""

    def test_builds_manifest_dict(self, tmp_path):
        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)
        from cardre.store.run_repo import RunRepository
        run_record = RunRepository(store).get(run_id)

        payload = build_manifest_payload(
            run_id=run_id,
            plan_version_id=pv_id,
            run_record=run_record,
            run_steps=[],
            execution_mode="full_plan",
            final_status="succeeded",
            finished_at=utc_now_iso(),
        )

        assert payload["run_id"] == run_id
        assert payload["status"] == "succeeded"
        assert payload["execution_mode"] == "full_plan"
        assert payload["steps"] == []
        assert "manifest_version" in payload


class TestStepAction:
    def test_step_action_reused(self):
        from cardre.domain.run import RunStep, RunStepStatus
        from cardre.execution.run_lifecycle import step_action
        fp = {"cardre_step_carried_forward": True}
        rs = RunStep("rs1", "r", "s", "pv", RunStepStatus.SUCCEEDED, "now", "now", fp, [], [])
        assert step_action(rs) == "reused"

    def test_step_action_executed(self):
        from cardre.domain.run import RunStep, RunStepStatus
        from cardre.execution.run_lifecycle import step_action
        rs = RunStep("rs2", "r", "s", "pv", RunStepStatus.SUCCEEDED, "now", "now", {}, [], [])
        assert step_action(rs) == "executed"


class TestFinaliseValidation:
    """finalise status validation inside the protected block."""

    def test_invalid_status_gets_run_finalisation_failed(self, tmp_path):
        """An invalid status string must raise and record RUN_FINALISATION_FAILED."""
        import pytest

        from cardre.execution.run_lifecycle import RunLifecycle
        from cardre.store.run_repo import RunRepository

        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        lifecycle = RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="full_plan",
        )
        with pytest.raises(ValueError):
            lifecycle.finalise("not-a-status")

        run = RunRepository(store).get(run_id)
        assert run["status"] == "failed"
        diags = RunRepository(store).get_diagnostics(run_id)
        assert any(d.get("code") == "RUN_FINALISATION_FAILED" for d in diags)

    def test_non_terminal_status_gets_run_finalisation_failed(self, tmp_path):
        """A valid but non-terminal RunStatus must raise and record
        RUN_FINALISATION_FAILED, transitioning the run to failed."""
        import pytest

        from cardre.domain.run import RunStatus
        from cardre.execution.run_lifecycle import RunLifecycle
        from cardre.store.run_repo import RunRepository

        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        lifecycle = RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="full_plan",
        )
        with pytest.raises(ValueError):
            lifecycle.finalise(RunStatus.RUNNING)

        run = RunRepository(store).get(run_id)
        assert run["status"] == "failed"
        diags = RunRepository(store).get_diagnostics(run_id)
        assert any(d.get("code") == "RUN_FINALISATION_FAILED" for d in diags)


class TestConcurrentFinalisation:
    """When two callers race to finalise the same run, the loser must not
    leave the manifest inconsistent with the database."""

    def test_loser_rewrites_manifest_to_match_winner(self, tmp_path):
        """If finalise_run loses the compare-and-set transition, it must
        rewrite the manifest to match the actual database status."""
        import pytest

        from cardre.execution.run_lifecycle import (
            RunFinalisation,
            RunLifecycleError,
            finalise_run,
        )
        from cardre.store.run_repo import RunRepository

        store = _make_store(tmp_path)
        _, pv_id, run_id = _seed_simple_run(store)

        # Winner — finalises as succeeded
        finalise_run(store, RunFinalisation(
            run_id=run_id, plan_version_id=pv_id,
            status="succeeded", execution_mode="full_plan",
            finished_at=utc_now_iso(),
        ))

        run = RunRepository(store).get(run_id)
        assert run["status"] == "succeeded"

        # Loser — tries to finalise as interrupted, but the run is already
        # succeeded. Must raise and rewrite the manifest.
        with pytest.raises(RunLifecycleError) as exc_info:
            finalise_run(store, RunFinalisation(
                run_id=run_id, plan_version_id=pv_id,
                status="interrupted", execution_mode="full_plan",
                finished_at=utc_now_iso(),
            ))
        assert exc_info.value.code == "RUN_ALREADY_FINALISED"
        assert exc_info.value.context["actual_status"] == "succeeded"

        # Run status must still be succeeded
        run = RunRepository(store).get(run_id)
        assert run["status"] == "succeeded"

        # Manifest must match the database, not the loser's intent
        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["status"] == "succeeded"
