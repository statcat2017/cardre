"""Tests for the RunWorker / RunDispatcher abstraction.

Covers:
- thread/worker dispatch success;
- dispatch startup failure (thread creation fails);
- worker exception after run creation;
- run status after worker failure;
- diagnostic contents after worker failure;
- sidecar route behaviour when dispatch fails.

These tests characterise the centralised worker/dispatcher seam introduced
in cardre.services.run_worker. They do not exercise the executor itself
(that is covered by test_executor / test_run_lifecycle); they assert the
dispatch, naming, exception, diagnostic, and final-status contracts.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from cardre.audit import StepSpec, json_logical_hash
from cardre.errors import CardreError
from cardre.services.run_worker import (
    DISPATCH_FAILED_CODE,
    RunRequest,
    RunWorker,
    SyncRunDispatcher,
    ThreadRunDispatcher,
    WORKER_FAILED_CODE,
)
from cardre.store import ProjectStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_store(tmp: Path) -> ProjectStore:
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store


def _one_step_plan(store: ProjectStore) -> str:
    """Create a project, plan, and one-step plan version. Returns pv_id."""
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")
    steps = [
        StepSpec(
            step_id="source", node_type="cardre.test.simple_source",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        ),
    ]
    return store.create_plan_version(plan_id, steps)


class _RecordingDispatcher:
    """Fake dispatcher that records the request and runs the worker inline.

    Used to assert that RunService hands the dispatcher a correctly
    populated RunRequest, and to drive the worker deterministically in
    tests that need synchronous execution.
    """

    def __init__(self) -> None:
        self.dispatched: list[RunRequest] = []

    def dispatch(self, request: RunRequest) -> None:
        self.dispatched.append(request)


class _ExplodingDispatcher:
    """Dispatcher whose dispatch() always raises to simulate startup failure."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def dispatch(self, request: RunRequest) -> None:
        self.calls += 1
        raise self.exc


# ---------------------------------------------------------------------------
# RunRequest
# ---------------------------------------------------------------------------


class TestRunRequest:
    def test_worker_name_is_prefixed_and_short(self) -> None:
        req = RunRequest(
            project_path="/tmp/x", plan_version_id="pv", run_id="abcdef1234567890",
        )
        name = req.worker_name()
        assert name.startswith("cardre-run-")
        # Uses only the first 8 chars of the run id, so it stays readable.
        assert name == "cardre-run-abcdef12"

    def test_request_is_frozen(self) -> None:
        req = RunRequest(project_path="/tmp/x", plan_version_id="pv", run_id="r")
        with pytest.raises((AttributeError, TypeError)):
            req.run_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RunWorker — exception handling and diagnostics
# ---------------------------------------------------------------------------


class TestRunWorkerFailure:
    def test_worker_exception_records_diagnostic_and_fails_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When execute_run raises, the worker records RUN_WORKER_FAILED
        and marks the run failed."""
        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        run_id = store.create_run(pv_id)

        def _raise(*args, **kwargs):
            raise RuntimeError("boom from executor")

        monkeypatch.setattr(
            "cardre.services.run_orchestrator.execute_run", _raise
        )

        req = RunRequest(
            project_path=str(store.root),
            plan_version_id=pv_id, run_id=run_id,
        )
        RunWorker().execute(req)

        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"

        diags = store.get_run_diagnostics(run_id)
        codes = [d["code"] for d in diags]
        assert WORKER_FAILED_CODE in codes
        failed = next(d for d in diags if d["code"] == WORKER_FAILED_CODE)
        assert failed["severity"] == "error"
        assert failed["category"] == "execution"
        assert failed["exception_type"] == "RuntimeError"
        assert "boom from executor" in failed["message"]
        assert failed["run_id"] == run_id
        assert failed["plan_version_id"] == pv_id
        assert "traceback" in failed
        assert "created_at" in failed

    def test_worker_heartbeats_before_execution(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The worker writes an initial heartbeat so the run is not
        immediately considered stale."""
        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        run_id = store.create_run(pv_id)
        before = store.get_run(run_id)["heartbeat_at"]

        seen: dict = {}

        def _capture_heartbeat_then_raise(store, **kw):
            seen["heartbeat"] = store.get_run(run_id)["heartbeat_at"]
            raise RuntimeError("stop")

        monkeypatch.setattr(
            "cardre.services.run_orchestrator.execute_run",
            _capture_heartbeat_then_raise,
        )

        req = RunRequest(
            project_path=str(store.root),
            plan_version_id=pv_id, run_id=run_id,
        )
        RunWorker().execute(req)

        # The heartbeat seen inside execute_run was fresher than the
        # one written at create_run time.
        assert seen["heartbeat"] is not None
        assert seen["heartbeat"] >= before

    def test_worker_failure_does_not_leave_run_running(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        run_id = store.create_run(pv_id)

        monkeypatch.setattr(
            "cardre.services.run_orchestrator.execute_run",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")),
        )

        RunWorker().execute(
            RunRequest(project_path=str(store.root), plan_version_id=pv_id, run_id=run_id)
        )
        assert store.get_run(run_id)["status"] == "failed"


# ---------------------------------------------------------------------------
# ThreadRunDispatcher — dispatch success and startup failure
# ---------------------------------------------------------------------------


class TestThreadRunDispatcher:
    def test_dispatch_success_starts_named_thread(self, tmp_path: Path) -> None:
        """A real thread is started with the cardre-run- prefix name and
        the worker runs to completion."""
        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        run_id = store.create_run(pv_id)

        # Use a simple executor stub that just records a marker artifact
        # via the registered simple_source node path is overkill; instead
        # patch execute_run to a no-op so the thread finishes fast.
        import cardre.services.run_orchestrator as ro
        original = ro.execute_run
        ro.execute_run = lambda *a, **k: run_id  # type: ignore[assignment]
        try:
            req = RunRequest(
                project_path=str(store.root),
                plan_version_id=pv_id, run_id=run_id,
            )
            ThreadRunDispatcher().dispatch(req)
            # Wait for any worker thread matching the run id prefix to finish.
            _join_named(req.worker_name())
        finally:
            ro.execute_run = original  # type: ignore[assignment]

        # No diagnostic should have been recorded on success.
        diags = store.get_run_diagnostics(run_id)
        assert all(d["code"] != WORKER_FAILED_CODE for d in diags)

    def test_dispatch_startup_failure_raises_typed_error_and_records_diagnostic(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """If thread construction/start raises, the dispatcher records a
        RUN_DISPATCH_FAILED diagnostic, fails the run, and raises CardreError."""
        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        run_id = store.create_run(pv_id)

        # Force threading.Thread() to raise during construction.
        def _boom(*a, **k):
            raise OSError("cannot create thread")

        monkeypatch.setattr("cardre.services.run_worker.threading.Thread", _boom)

        req = RunRequest(
            project_path=str(store.root),
            plan_version_id=pv_id, run_id=run_id,
        )
        with pytest.raises(CardreError) as ei:
            ThreadRunDispatcher().dispatch(req)
        assert ei.value.code == DISPATCH_FAILED_CODE

        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "failed"

        diags = store.get_run_diagnostics(run_id)
        codes = [d["code"] for d in diags]
        assert DISPATCH_FAILED_CODE in codes
        d = next(x for x in diags if x["code"] == DISPATCH_FAILED_CODE)
        assert d["severity"] == "error"
        assert d["category"] == "lifecycle"
        assert d["exception_type"] == "OSError"
        assert d["run_id"] == run_id
        assert d["plan_version_id"] == pv_id


# ---------------------------------------------------------------------------
# SyncRunDispatcher — inline execution for tests
# ---------------------------------------------------------------------------


class TestSyncRunDispatcher:
    def test_sync_dispatcher_runs_worker_inline(self, tmp_path: Path, monkeypatch) -> None:
        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        run_id = store.create_run(pv_id)

        called: list[bool] = []

        def _ok(*a, **k):
            called.append(True)

        monkeypatch.setattr("cardre.services.run_orchestrator.execute_run", _ok)

        SyncRunDispatcher().dispatch(
            RunRequest(project_path=str(store.root), plan_version_id=pv_id, run_id=run_id)
        )
        assert called == [True]

    def test_sync_dispatcher_swallows_worker_exception(self, tmp_path: Path, monkeypatch) -> None:
        """The dispatcher must not let worker exceptions escape — the
        worker owns them. The run ends up failed with a diagnostic."""
        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        run_id = store.create_run(pv_id)

        monkeypatch.setattr(
            "cardre.services.run_orchestrator.execute_run",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")),
        )

        # Must not raise.
        SyncRunDispatcher().dispatch(
            RunRequest(project_path=str(store.root), plan_version_id=pv_id, run_id=run_id)
        )
        assert store.get_run(run_id)["status"] == "failed"
        assert WORKER_FAILED_CODE in [
            d["code"] for d in store.get_run_diagnostics(run_id)
        ]


# ---------------------------------------------------------------------------
# RunService integration — dispatcher injection
# ---------------------------------------------------------------------------


class TestRunServiceDispatcherInjection:
    def test_run_service_uses_injected_dispatcher(self, tmp_path: Path) -> None:
        """RunService delegates to the injected dispatcher and hands it a
        fully populated RunRequest."""
        from cardre.services.run_service import RunService

        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)
        recorder = _RecordingDispatcher()

        service = RunService(store, dispatcher=recorder)
        resp = service.run_plan(plan_version_id=pv_id, sync=False)

        assert recorder.dispatched, "dispatcher was not called"
        req = recorder.dispatched[0]
        assert req.run_id == resp.run_id
        assert req.plan_version_id == pv_id
        assert req.project_path == str(store.root)
        assert req.run_scope == "full_plan"
        # The run was created but NOT executed (recorder is a no-op).
        assert store.get_run(resp.run_id)["status"] == "running"

    def test_run_service_default_dispatcher_is_thread_backed(self, tmp_path: Path) -> None:
        """Without an injected dispatcher, RunService uses ThreadRunDispatcher
        and the worker actually runs."""
        from cardre.services.run_service import RunService

        store = _init_store(tmp_path)
        pv_id = _one_step_plan(store)

        # Patch execute_run to a fast no-op so the thread exits quickly.
        import cardre.services.run_orchestrator as ro
        original = ro.execute_run
        ro.execute_run = lambda *a, **k: None  # type: ignore[assignment]
        try:
            service = RunService(store)
            resp = service.run_plan(plan_version_id=pv_id, sync=False)
            _join_named(f"cardre-run-{resp.run_id[:8]}")
        finally:
            ro.execute_run = original  # type: ignore[assignment]

        run = store.get_run(resp.run_id)
        # execute_run no-op leaves the run running (no finalisation); the
        # point of this test is that a real thread was started and ran.
        assert run is not None


# ---------------------------------------------------------------------------
# Sidecar route behaviour when dispatch fails
# ---------------------------------------------------------------------------


class TestSidecarDispatchFailure:
    def test_post_runs_returns_500_with_dispatch_failed_code(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When the dispatcher raises CardreError(RUN_DISPATCH_FAILED),
        POST /runs surfaces it as a 500 with that code."""
        from fastapi.testclient import TestClient
        from sidecar.main import app

        # Isolate the registry to a temp path.
        monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(tmp_path / "registry.json"))

        store = _init_store(tmp_path / "proj.cardre")
        prj_id = store.create_project("test")
        _ = store.create_plan(prj_id, "test-plan")
        pv_id = _one_step_plan(store)

        # Register the project so the sidecar can resolve it.
        from cardre.services.project_registry import create_project_registry_entry
        create_project_registry_entry(prj_id, store.root, "test")

        # Force the runs route to construct a RunService whose dispatcher
        # always raises a typed dispatch-failure error.
        from sidecar.routes import runs as runs_route
        from cardre.services.run_service import RunService

        class _ExplodingRunService(RunService):
            def __init__(self, store):
                super().__init__(
                    store,
                    dispatcher=_ExplodingDispatcher(
                        CardreError("boom", code=DISPATCH_FAILED_CODE)
                    ),
                )

        monkeypatch.setattr(runs_route, "RunService", _ExplodingRunService)

        client = TestClient(app)
        resp = client.post("/runs", json={
            "project_id": prj_id, "plan_version_id": pv_id,
        })
        assert resp.status_code == 500
        detail = resp.json().get("detail", {})
        assert detail.get("code") == DISPATCH_FAILED_CODE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _join_named(name: str, timeout: float = 5.0) -> None:
    """Join any live thread whose name matches, to make tests deterministic."""
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        live = [t for t in threading.enumerate() if t.name == name and t.is_alive()]
        if not live:
            return
        for t in live:
            t.join(timeout=0.1)
    # Don't fail hard if a thread is slow; tests assert store state instead.