"""RunDispatcher port contract tests (Batch 07g).

Runs the same behavioural contract against both the synchronous and
thread-based dispatchers, preserving the semantics formerly covered by
``test_run_dispatch.py`` (dispatch, status reporting, shutdown).

Worker completion is signalled with ``threading.Event`` objects so the
thread-based assertions never race the background worker.
"""

from __future__ import annotations

import threading

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
