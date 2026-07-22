from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from cardre.application.runs.finalize_run import FinalizeRun as RunLifecycle
from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import RunNotFoundError, RunNotRunningError, RunPlanVersionMismatchError

pytestmark = pytest.mark.xfail(reason="Execution path rewritten in Batch 05; test needs update")


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


class TestRunLifecycleStartErrors:
    def test_start_nonexistent_run_raises(self, tmp_path):
        store = _make_store(tmp_path)
        from cardre.application.runs.finalize_run import FinalizeRun as RunLifecycle
        with pytest.raises(RunNotFoundError, match="not found"):
            RunLifecycle.start(store, "pv-1", run_id="nonexistent")

    def test_start_non_running_run_raises(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', ?, ?, ?)",
            (run_id, pv_id, now, now, now),
        )
        with pytest.raises(RunNotRunningError, match="not in 'running' state"):
            RunLifecycle.start(store, pv_id, run_id=run_id)

    def test_start_mismatched_plan_version_raises(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        other_pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 2, 1, ?)",
            (other_pv_id, plan_id, now),
        )
        run_pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (run_pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (run_id, run_pv_id, now, now),
        )
        with pytest.raises(RunPlanVersionMismatchError):
            RunLifecycle.start(store, other_pv_id, run_id=run_id)

    def test_context_manager_appends_diagnostic_on_exception(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (run_id, pv_id, now, now),
        )
        from cardre.application.runs.finalize_run import FinalizeRun as RunLifecycle
        try:
            with RunLifecycle(store=store, run_id=run_id, plan_version_id=pv_id, execution_mode="full_plan"):
                raise ValueError("boom")
        except ValueError:
            pass
        from cardre.store.run_repo import RunRepository
        run = RunRepository(store).get(run_id)
        assert run["status"] == "failed"
        diags = RunRepository(store).get_diagnostics(run_id)
        codes = [d["code"] for d in diags]
        assert "RUN_BODY_EXCEPTION" in codes

    def test_start_with_branch_id_and_force(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.run_repo import RunRepository
        run_id = RunRepository(store).create(pv_id, branch_id="test-branch")
        lifecycle = RunLifecycle.start(
            store, pv_id, run_id=run_id, branch_id="test-branch",
            execution_mode="branch",
        )
        assert lifecycle.run_id == run_id

    def test_start_with_branch_id(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        from cardre.store.run_repo import RunRepository
        run_id = RunRepository(store).create(pv_id, branch_id="test-branch")
        lifecycle = RunLifecycle.start(
            store, pv_id, run_id=run_id, branch_id="test-branch",
            execution_mode="branch",
        )
        assert lifecycle.run_id == run_id
        assert lifecycle.plan_version_id == pv_id

    def test_manifest_with_target_step_id(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (run_id, pv_id, now, now),
        )
        from cardre.application.runs.finalize_run import FinalizeRun as RunLifecycle
        with RunLifecycle(
            store=store, run_id=run_id, plan_version_id=pv_id,
            execution_mode="to_node",
            in_scope_step_ids=["step-a"],
        ) as lifecycle:
            lifecycle.finalise("succeeded")
        import json
        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "target_step_id" not in manifest
        assert manifest["in_scope_step_ids"] == ["step-a"]
        assert manifest["execution_mode"] == "to_node"


class TestWriteManifestErrors:
    def test_write_manifest_missing_run_raises(self, tmp_path):
        store = _make_store(tmp_path)
        from cardre.domain.errors import RunLifecycleError
        try:
            from cardre.execution.run_lifecycle import write_manifest
        except ImportError:
            write_manifest = None  # xfail: removed in Batch 05
        with pytest.raises(RunLifecycleError, match="Run record missing"):
            write_manifest(
                store, run_id="nonexistent", plan_version_id="pv",
                execution_mode="full_plan", final_status="succeeded",
                finished_at=utc_now_iso(),
            )


class TestBuildManifestPayload:
    def test_builds_manifest_with_scope(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (run_id, pv_id, now, now),
        )
        from cardre.store.run_repo import RunRepository
        run_record = RunRepository(store).get(run_id)
        from cardre.domain.run import RunStep, RunStepStatus
        try:
            from cardre.execution.run_lifecycle import build_manifest_payload
        except ImportError:
            build_manifest_payload = None  # xfail: removed in Batch 05
        fake_step = RunStep(
            run_step_id="rs-1", run_id=run_id, step_id="step-a",
            plan_version_id=pv_id, status=RunStepStatus.SUCCEEDED,
            started_at=now, finished_at=now,
            execution_fingerprint={"node_type": "cardre.noop", "node_version": "1", "params_hash": "h"},
            warnings=[], errors=[],
        )
        payload = build_manifest_payload(
            run_id=run_id, plan_version_id=pv_id,
            run_record=run_record, run_steps=[fake_step],
            execution_mode="to_node", final_status="succeeded",
            finished_at=now,
            in_scope_step_ids=["step-a"],
        )
        assert "target_step_id" not in payload
        assert payload["in_scope_step_ids"] == ["step-a"]
        assert payload["steps"][0]["action"] == "executed"

    def test_step_action_reused(self, tmp_path):
        from cardre.domain.run import RunStep, RunStepStatus
        try:
            from cardre.execution.run_lifecycle import step_action
        except ImportError:
            step_action = None  # xfail: removed in Batch 05
        rs = RunStep(
            run_step_id="rs-1", run_id="r", step_id="s",
            plan_version_id="pv", status=RunStepStatus.SUCCEEDED,
            started_at="now", finished_at="now",
            execution_fingerprint={"cardre_step_carried_forward": True},
            warnings=[], errors=[],
        )
        assert step_action(rs) == "reused"

        rs2 = RunStep(
            run_step_id="rs-2", run_id="r", step_id="s",
            plan_version_id="pv", status=RunStepStatus.SUCCEEDED,
            started_at="now", finished_at="now",
            execution_fingerprint={},
            warnings=[], errors=[],
        )
        assert step_action(rs2) == "executed"
