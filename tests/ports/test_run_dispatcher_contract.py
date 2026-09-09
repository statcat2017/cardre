"""RunDispatcher port contract tests (Batch 07g).

Runs the same behavioural contract against both the synchronous and
thread-based dispatchers, preserving the semantics formerly covered by
``test_run_dispatch.py`` (dispatch, status reporting, shutdown).

Worker completion is signalled with ``threading.Event`` objects so the
thread-based assertions never race the background worker.
"""

from __future__ import annotations

import threading

import pytest

from cardre.adapters.dispatch.sync_dispatcher import SyncRunDispatcher
from cardre.adapters.dispatch.thread_dispatcher import ThreadRunDispatcher
from cardre.application.ports.run_dispatcher import RunRequest


def _request(run_id: str = "run-1") -> RunRequest:
    return RunRequest(run_id=run_id, plan_version_id="pv-1")


class TestRunDispatcherContract:
    def test_sync_dispatch_invokes_execute_run(self):
        captured: list[str] = []
        dispatcher = SyncRunDispatcher(lambda command: captured.append(command.run_id))
        dispatcher.dispatch(_request("run-1"))
        assert captured == ["run-1"]
        dispatcher.shutdown()

    def test_thread_dispatch_invokes_execute_run(self):
        captured: list[str] = []
        started = threading.Event()
        finished = threading.Event()

        def execute(command) -> None:
            captured.append(command.run_id)
            started.set()
            finished.set()

        dispatcher = ThreadRunDispatcher(execute)
        dispatcher.dispatch(_request("run-1"))
        assert started.wait(timeout=5), "worker never started"
        assert finished.wait(timeout=5), "worker never finished"
        assert captured == ["run-1"]
        dispatcher.shutdown()

    def test_sync_reports_completed(self):
        dispatcher = SyncRunDispatcher(lambda command: None)
        dispatcher.dispatch(_request("run-1"))
        assert dispatcher.get_status("run-1") == "completed"
        dispatcher.shutdown()

    def test_sync_reports_unknown_for_undispatched_run(self):
        dispatcher = SyncRunDispatcher(lambda command: None)
        dispatcher.dispatch(_request("run-1"))
        # An unknown Run must be distinguishable from a completed Run, so a
        # Run that was never dispatched cannot be reported as completed.
        assert dispatcher.get_status("never-dispatched") != "completed"
        dispatcher.shutdown()

    def test_thread_reports_unknown_for_undispatched_run(self):
        finished = threading.Event()

        def execute(command) -> None:
            finished.set()

        thread = ThreadRunDispatcher(execute)
        try:
            thread.dispatch(_request("run-1"))
            assert finished.wait(timeout=5), "worker never finished"
            assert thread.get_status("run-1") == "completed"
            # An unknown Run ID must not be confused with a completed Run.
            assert thread.get_status("never-dispatched") != "completed"
        finally:
            thread.shutdown()

    def test_sync_reports_failed_when_callback_raises(self):
        def execute(command) -> None:
            raise RuntimeError("boom")

        dispatcher = SyncRunDispatcher(execute)
        with pytest.raises(RuntimeError, match="boom"):
            dispatcher.dispatch(_request("run-1"))
        # A raising callback must not make the dispatched Run report completed.
        assert dispatcher.get_status("run-1") != "completed"
        dispatcher.shutdown()

    def test_thread_reports_failed_when_callback_raises(self):
        started = threading.Event()
        finished = threading.Event()

        def execute(command) -> None:
            started.set()
            finished.set()
            raise RuntimeError("boom")

        thread = ThreadRunDispatcher(execute)
        try:
            thread.dispatch(_request("run-1"))
            assert started.wait(timeout=5), "worker never started"
            assert finished.wait(timeout=5), "worker never finished"
            # A raising callback must not make the dispatched Run report
            # completed; it must be reported as failed. Poll because the worker
            # records the failure after the callback returns/raises.
            deadline = 5
            while thread.get_status("run-1") == "running" and deadline > 0:
                threading.Event().wait(0.05)
                deadline -= 0.05
            assert thread.get_status("run-1") == "failed"
        finally:
            thread.shutdown()
    def test_thread_reports_running_then_completed(self):
        started = threading.Event()
        finished = threading.Event()

        def execute(command) -> None:
            started.set()
            finished.wait(timeout=5)

        thread = ThreadRunDispatcher(execute)
        thread.dispatch(_request("run-1"))
        try:
            assert started.wait(timeout=5), "worker never started"
            assert thread.get_status("run-1") == "running"
        finally:
            finished.set()
        deadline = 5
        while thread.get_status("run-1") == "running" and deadline > 0:
            threading.Event().wait(0.05)
            deadline -= 0.05
        assert thread.get_status("run-1") == "completed"
        thread.shutdown()

    def test_thread_redispatched_completed_run_reports_queued_then_running_then_completed(self):
        """A run that previously completed and is legitimately redispatched must
        discard old completion bookkeeping at admission: queued while waiting,
        running while executing, completed after a successful attempt."""
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = 0

        def execute(command) -> None:
            nonlocal calls
            calls += 1
            started.set()
            release.wait(timeout=5)
            finished.set()

        thread = ThreadRunDispatcher(execute, max_workers=1)
        try:
            # First dispatch completes.
            thread.dispatch(_request("run-1"))
            assert started.wait(timeout=5), "worker never started"
            release.set()
            assert finished.wait(timeout=5), "worker never finished"
            assert thread.get_status("run-1") == "completed"

            # Legitimate redispatch of the same run: old completion bookkeeping
            # must be discarded at admission, so it reports queued while waiting.
            started.clear()
            release.clear()
            finished.clear()
            thread.dispatch(_request("run-1"))
            assert thread.get_status("run-1") == "queued"
            assert started.wait(timeout=5), "worker never started on redispatch"
            assert thread.get_status("run-1") == "running"
            release.set()
            assert finished.wait(timeout=5), "worker never finished on redispatch"
            assert thread.get_status("run-1") == "completed"
            assert calls == 2
        finally:
            release.set()
            thread.shutdown()
