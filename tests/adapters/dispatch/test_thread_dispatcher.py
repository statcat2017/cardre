"""ThreadRunDispatcher behavior tests (Batch 07g).

Preserves the semantics of the pre-Batch-05 ``test_run_dispatch.py``:
duplicate-dispatch rejection, active/completed status reporting, and
``max_workers`` enforcement. The dispatcher now takes an injected
``execute_run`` callable instead of calling the removed ``RunWorker``.
"""

from __future__ import annotations

import threading

import pytest

from cardre.adapters.dispatch.thread_dispatcher import ThreadRunDispatcher
from cardre.application.ports.run_dispatcher import RunRequest


def _request(run_id: str = "run-1") -> RunRequest:
    return RunRequest(run_id=run_id, plan_version_id="pv-1")


def _started_release() -> tuple[list[str], threading.Event, threading.Event]:
    """Return (executed_run_ids, started_event, release_event) for a blocking
    execute_run fake."""
    executed: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def execute(command) -> None:
        executed.append(command.run_id)
        started.set()
        release.wait(timeout=5)

    return executed, started, release, execute


def test_dispatcher_rejects_duplicate_dispatch_for_same_run():
    """Dispatching the same run_id twice must reject the second dispatch."""
    _, started, release, execute = _started_release()
    dispatcher = ThreadRunDispatcher(execute)

    dispatcher.dispatch(_request("run-1"))
    try:
        assert started.wait(timeout=2)
        with pytest.raises(RuntimeError) as exc_info:
            dispatcher.dispatch(_request("run-1"))
        assert "already" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()
    finally:
        release.set()
        dispatcher.shutdown()


def test_dispatcher_reports_running_then_completed(monkeypatch):
    """get_status reports 'running' while active and 'completed' after."""
    _, started, release, execute = _started_release()
    dispatcher = ThreadRunDispatcher(execute)

    dispatcher.dispatch(_request("run-1"))
    try:
        assert started.wait(timeout=2)
        assert dispatcher.get_status("run-1") == "running"
    finally:
        release.set()

    # Wait for the worker to finish; then status flips to completed.
    deadline = 5
    while dispatcher.get_status("run-1") == "running" and deadline > 0:
        threading.Event().wait(0.05)
        deadline -= 0.05
    assert dispatcher.get_status("run-1") == "completed"
    dispatcher.shutdown()


def test_dispatcher_enforces_max_workers_bound():
    """A dispatcher with max_workers=1 rejects a second concurrent dispatch."""
    _, started, release, execute = _started_release()
    dispatcher = ThreadRunDispatcher(execute, max_workers=1)

    dispatcher.dispatch(_request("run-1"))
    try:
        assert started.wait(timeout=2)
        with pytest.raises(RuntimeError) as exc_info:
            dispatcher.dispatch(_request("run-2"))
        assert "workers" in str(exc_info.value).lower()
    finally:
        release.set()
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
    executed: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def execute(command) -> None:
        executed.append(command.run_id)
        started.set()
        release.wait(timeout=5)

    dispatcher = ThreadRunDispatcher(execute, max_workers=2)
    dispatcher.dispatch(_request("run-1"))
    try:
        assert started.wait(timeout=2)
        dispatcher.dispatch(_request("run-2"))
        assert dispatcher.get_status("run-2") == "running"
    finally:
        release.set()
        dispatcher.shutdown()
    assert sorted(executed) == ["run-1", "run-2"]
