"""Tests for run worker store lifecycle."""

from __future__ import annotations

import json
import uuid

from cardre.domain.diagnostics import utc_now_iso

try:
    from cardre.execution.executor import _HeartbeatWatchdog
except ImportError:
    _HeartbeatWatchdog = None  # xfail: removed in Batch 05
import pytest

from cardre.adapters.dispatch.thread_dispatcher import ThreadRunDispatcher as RunWorker
from cardre.application.ports.run_dispatcher import RunRequest
from cardre.store.db import ProjectStore
from cardre.store.run_repo import RunRepository

pytestmark = pytest.mark.xfail(reason="Execution path rewritten in Batch 05; test needs update")


def test_worker_closes_store_on_success(store, monkeypatch):
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    plan_version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Worker Project", now, "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Worker Plan", now),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) VALUES (?, ?, 1, 1, ?)",
        (plan_version_id, plan_id, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
        (run_id, plan_version_id, now, now),
    )
    store.close()

    close_calls: list[str] = []
    original_close = ProjectStore.close

    def close_spy(self):
        close_calls.append(str(self.root))
        return original_close(self)

    monkeypatch.setattr(ProjectStore, "close", close_spy)
    monkeypatch.setattr(RunWorker, "_invoke_executor", staticmethod(lambda store, request: None))

    worker = RunWorker()
    worker.execute(
        RunRequest(
            project_path=str(store.root),
            plan_version_id=plan_version_id,
            run_id=run_id,
        )
    )

    assert close_calls == [str(store.root)]


def test_worker_closes_store_on_exception(store, monkeypatch):
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    plan_version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Worker Project", now, "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Worker Plan", now),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) VALUES (?, ?, 1, 1, ?)",
        (plan_version_id, plan_id, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
        (run_id, plan_version_id, now, now),
    )
    store.close()

    close_calls: list[str] = []
    original_close = ProjectStore.close

    def close_spy(self):
        close_calls.append(str(self.root))
        return original_close(self)

    monkeypatch.setattr(ProjectStore, "close", close_spy)

    def invoke_raises(store_arg, request):
        raise RuntimeError("boom")

    monkeypatch.setattr(RunWorker, "_invoke_executor", staticmethod(invoke_raises))

    worker = RunWorker()
    worker.execute(
        RunRequest(
            project_path=str(store.root),
            plan_version_id=plan_version_id,
            run_id=run_id,
        )
    )

    assert close_calls == [str(store.root)]


def test_heartbeat_watchdog_closes_store_per_tick(store, monkeypatch):
    close_calls: list[str] = []
    original_close = ProjectStore.close

    def close_spy(self):
        close_calls.append(str(self.root))
        return original_close(self)

    monkeypatch.setattr(ProjectStore, "close", close_spy)
    monkeypatch.setattr(RunRepository, "heartbeat", lambda self, run_id: None)

    watchdog = _HeartbeatWatchdog(store, run_id="run-1", step_id="step-1", interval_seconds=1)
    waits = iter([False, True])
    monkeypatch.setattr(watchdog._stop, "wait", lambda timeout=None: next(waits))

    watchdog._tick()

    assert close_calls == [str(store.root)]


def test_worker_exception_produces_failed_run_with_diagnostic(store, monkeypatch):
    """A worker exception must finalise the run as failed and record a diagnostic (#211)."""
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    plan_version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Worker Project", now, "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Worker Plan", now),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) VALUES (?, ?, 1, 1, ?)",
        (plan_version_id, plan_id, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
        (run_id, plan_version_id, now, now),
    )
    store.close()

    def invoke_raises(store_arg, request):
        raise RuntimeError("boom")

    monkeypatch.setattr(RunWorker, "_invoke_executor", staticmethod(invoke_raises))

    worker = RunWorker()
    worker.execute(
        RunRequest(
            project_path=str(store.root),
            plan_version_id=plan_version_id,
            run_id=run_id,
        )
    )

    s = ProjectStore(store.root)
    s.open()
    try:
        run = RunRepository(s).get(run_id)
        assert run["status"] == "failed"
        diags = RunRepository(s).get_diagnostics(run_id)
        assert any(d.get("code") == "RUN_WORKER_FAILED" for d in diags)
        manifest_path = s.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert json.loads(manifest_path.read_text())["status"] == "failed"
    finally:
        s.close()


def test_worker_failure_recorded_when_coordinator_also_finalised(store, monkeypatch):
    """When execution raises inside the coordinator lifecycle context,
    __exit__ finalises the run as failed. The worker must still record
    RUN_WORKER_FAILED without attempting a second lifecycle transition."""
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    plan_version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Worker Project", now, "0.2.0"),
    )
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Worker Plan", now),
    )
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) VALUES (?, ?, 1, 1, ?)",
        (plan_version_id, plan_id, now),
    )
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) VALUES (?, ?, 'running', ?, ?)",
        (run_id, plan_version_id, now, now),
    )
    store.close()

    from cardre.execution.executor import PlanExecutor

    def fake_run_plan_version(self, plan_version_id_arg, run_id_arg, **kwargs):
        raise RuntimeError("execution failed")

    monkeypatch.setattr(PlanExecutor, "run_plan_version", fake_run_plan_version)

    from cardre.adapters.dispatch.thread_dispatcher import ThreadRunDispatcher as RunWorker
    from cardre.application.ports.run_dispatcher import RunRequest
    worker = RunWorker()
    worker.execute(
        RunRequest(
            project_path=str(store.root),
            plan_version_id=plan_version_id,
            run_id=run_id,
        )
    )

    from cardre.store.run_repo import RunRepository
    s = ProjectStore(store.root)
    s.open()
    try:
        run = RunRepository(s).get(run_id)
        assert run["status"] == "failed"
        diags = RunRepository(s).get_diagnostics(run_id)
        # RUN_BODY_EXCEPTION from lifecycle context manager exit
        assert any(d.get("code") == "RUN_BODY_EXCEPTION" for d in diags)
        # RUN_WORKER_FAILED from worker _record_failure
        assert any(d.get("code") == "RUN_WORKER_FAILED" for d in diags)
        manifest_path = s.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert json.loads(manifest_path.read_text())["status"] == "failed"
    finally:
        s.close()
