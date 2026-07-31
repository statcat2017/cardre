"""ThreadRunDispatcher behavior tests (Batch 07g).

Preserves the semantics of the pre-Batch-05 ``test_run_dispatch.py``:
duplicate-dispatch rejection, active/completed status reporting, and
``max_workers`` enforcement. The dispatcher now takes an injected
``execute_run`` callable instead of calling the removed ``RunWorker``.

Determinism: every worker signals per-run ``started`` and ``finished``
``threading.Event`` objects so assertions never race the worker thread.
"""

from __future__ import annotations

import threading

import pytest

from cardre.adapters.dispatch.thread_dispatcher import ThreadRunDispatcher
from cardre.application.ports.run_dispatcher import RunRequest


def _request(run_id: str = "run-1") -> RunRequest:
    return RunRequest(run_id=run_id, plan_version_id="pv-1")


class _BlockingHarness:
    """Runs a blocking ``execute_run`` fake with deterministic events.

    ``started[run_id]`` is set when the worker begins; ``finished[run_id]``
    is set when the worker returns; ``release[run_id]`` unblocks it.
    """

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.started: dict[str, threading.Event] = {}
        self.finished: dict[str, threading.Event] = {}
        self.release: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def execute(self, command) -> None:
        run_id = command.run_id
        started = self.started.setdefault(run_id, threading.Event())
        finished = self.finished.setdefault(run_id, threading.Event())
        release = self.release.setdefault(run_id, threading.Event())
        with self._lock:
            self.executed.append(run_id)
        started.set()
        release.wait(timeout=5)
        finished.set()

    def wait_started(self, run_id: str, timeout: float = 5) -> None:
        assert self.started[run_id].wait(timeout), f"worker {run_id} never started"

    def wait_finished(self, run_id: str, timeout: float = 5) -> None:
        assert self.finished[run_id].wait(timeout), f"worker {run_id} never finished"


def test_dispatcher_rejects_duplicate_dispatch_for_same_run():
    """Dispatching the same run_id twice must reject the second dispatch."""
    harness = _BlockingHarness()
    dispatcher = ThreadRunDispatcher(harness.execute)

    dispatcher.dispatch(_request("run-1"))
    try:
        harness.wait_started("run-1")
        with pytest.raises(RuntimeError) as exc_info:
            dispatcher.dispatch(_request("run-1"))
        assert "already" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()
    finally:
        harness.release["run-1"].set()
        harness.wait_finished("run-1")
        dispatcher.shutdown()


def test_dispatcher_reports_running_then_completed():
    """get_status reports 'running' while active and 'completed' after."""
    harness = _BlockingHarness()
    dispatcher = ThreadRunDispatcher(harness.execute)

    dispatcher.dispatch(_request("run-1"))
    try:
        harness.wait_started("run-1")
        assert dispatcher.get_status("run-1") == "running"
    finally:
        harness.release["run-1"].set()
        harness.wait_finished("run-1")
    assert dispatcher.get_status("run-1") == "completed"
    dispatcher.shutdown()


def test_dispatcher_enforces_max_workers_bound():
    """A dispatcher with max_workers=1 rejects a second concurrent dispatch."""
    harness = _BlockingHarness()
    dispatcher = ThreadRunDispatcher(harness.execute, max_workers=1)

    dispatcher.dispatch(_request("run-1"))
    try:
        harness.wait_started("run-1")
        with pytest.raises(RuntimeError) as exc_info:
            dispatcher.dispatch(_request("run-2"))
        assert "workers" in str(exc_info.value).lower()
    finally:
        harness.release["run-1"].set()
        harness.wait_finished("run-1")
        dispatcher.shutdown()


def test_dispatcher_rejects_dispatch_after_shutdown():
    """dispatch() after shutdown() raises RuntimeError."""
    dispatcher = ThreadRunDispatcher(lambda command: None)
    dispatcher.shutdown()
    with pytest.raises(RuntimeError) as exc_info:
        dispatcher.dispatch(_request("run-1"))
    assert "shut down" in str(exc_info.value).lower()


def test_dispatcher_executes_concurrent_runs_up_to_max_workers():
    """Two runs dispatch concurrently when max_workers=2."""
    harness = _BlockingHarness()
    dispatcher = ThreadRunDispatcher(harness.execute, max_workers=2)

    dispatcher.dispatch(_request("run-1"))
    harness.wait_started("run-1")
    dispatcher.dispatch(_request("run-2"))
    harness.wait_started("run-2")
    try:
        assert dispatcher.get_status("run-1") == "running"
        assert dispatcher.get_status("run-2") == "running"
    finally:
        for run_id in ("run-1", "run-2"):
            harness.release[run_id].set()
        for run_id in ("run-1", "run-2"):
            harness.wait_finished(run_id)
    assert sorted(harness.executed) == ["run-1", "run-2"]
    dispatcher.shutdown()
