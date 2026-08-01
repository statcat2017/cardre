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

    The event triplet for each run is pre-created by ``events()`` BEFORE the
    run is dispatched, so the test thread can safely wait on it immediately
    after ``dispatch()`` returns (no thread-startup race).
    """

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.started: dict[str, threading.Event] = {}
        self.finished: dict[str, threading.Event] = {}
        self.release: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def events(self, run_id: str) -> tuple[threading.Event, threading.Event, threading.Event]:
        """Pre-create (started, finished, release) events for a run."""
        started = threading.Event()
        finished = threading.Event()
        release = threading.Event()
        with self._lock:
            self.started[run_id] = started
            self.finished[run_id] = finished
            self.release[run_id] = release
        return started, finished, release

    def execute(self, command) -> None:
        run_id = command.run_id
        started = self.started[run_id]
        finished = self.finished[run_id]
        release = self.release[run_id]
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

    harness.events("run-1")
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

    harness.events("run-1")
    dispatcher.dispatch(_request("run-1"))
    try:
        harness.wait_started("run-1")
        assert dispatcher.get_status("run-1") == "running"
    finally:
        harness.release["run-1"].set()
        harness.wait_finished("run-1")
    assert dispatcher.get_status("run-1") == "completed"
    dispatcher.shutdown()


def test_dispatcher_queues_beyond_max_workers():
    """A dispatcher with max_workers=1 queues a second dispatch instead of
    rejecting it, so durable reconciliation never strands a pending run."""
    harness = _BlockingHarness()
    dispatcher = ThreadRunDispatcher(harness.execute, max_workers=1)

    harness.events("run-1")
    harness.events("run-2")
    dispatcher.dispatch(_request("run-1"))
    harness.wait_started("run-1")
    # Second dispatch is admitted into the queue (not rejected).
    dispatcher.dispatch(_request("run-2"))
    assert dispatcher.active_count == 1
    assert dispatcher.queued_count == 1
    try:
        assert dispatcher.get_status("run-2") == "completed"  # not yet running
        # Release the first worker; the queued run must then execute.
        harness.release["run-1"].set()
        harness.wait_started("run-2")
        assert dispatcher.get_status("run-2") == "running"
    finally:
        for run_id in ("run-1", "run-2"):
            harness.release[run_id].set()
        for run_id in ("run-1", "run-2"):
            harness.wait_finished(run_id)
    assert sorted(harness.executed) == ["run-1", "run-2"]
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

    harness.events("run-1")
    harness.events("run-2")
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


def test_dispatch_after_shutdown_is_rejected():
    """A dispatch racing shutdown's flag flip must be admitted atomically and
    then drained; a dispatch after shutdown is rejected (P2-2/P2-A)."""
    harness = _BlockingHarness()
    cancelled: list[str] = []

    def cancel(request):
        cancelled.append(request.run_id)
        harness.release[request.run_id].set()  # cooperative cancel unblocks the worker

    dispatcher = ThreadRunDispatcher(harness.execute, max_workers=4, cancel_run=cancel)

    harness.events("run-1")
    dispatcher.dispatch(_request("run-1"))
    harness.wait_started("run-1")
    # shutdown flips the flag under the same lock that admits dispatch, then
    # requests cooperative cancellation of the active worker and drains it.
    dispatcher.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        dispatcher.dispatch(_request("run-2"))
    harness.wait_finished("run-1")
    # The worker was drained by shutdown; no active work remains.
    assert cancelled == ["run-1"], "shutdown must cooperatively cancel active runs"
    assert dispatcher.get_status("run-1") == "completed"
    assert dispatcher.active_count == 0
    assert dispatcher.drain_failed is False


def test_shutdown_reports_failed_drain_when_worker_does_not_exit():
    """If a worker ignores cooperative cancellation and stays alive past the
    drain window, shutdown reports a failed drain instead of silently
    abandoning a daemon worker (P2-A)."""
    harness = _BlockingHarness()
    # No cancel hook: the worker blocks forever and shutdown cannot unblock it.
    dispatcher = ThreadRunDispatcher(harness.execute, max_workers=1, drain_timeout_seconds=0.1)

    harness.events("run-1")
    dispatcher.dispatch(_request("run-1"))
    harness.wait_started("run-1")
    try:
        dispatcher.shutdown()
        assert dispatcher.drain_failed is True, "worker left alive must be reported"
        assert dispatcher.active_count == 1
    finally:
        harness.release["run-1"].set()
        harness.wait_finished("run-1")
    # After the worker finally exits, active_count drops to zero.
    assert dispatcher.active_count == 0
