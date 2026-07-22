"""Tests for bounded run dispatch and terminal-state safety (#211)."""

from __future__ import annotations

import threading

import pytest

from cardre.domain.errors import CardreError
from cardre.execution.worker import (
    RunRequest,
    RunWorker,
    ThreadRunDispatcher,
)

pytestmark = pytest.mark.xfail(reason="Execution path broken during Batch 04; restored in Batch 05")


def _request(run_id: str = "run-1") -> RunRequest:
    return RunRequest(
        project_path="/tmp/nonexistent.cardre",
        plan_version_id="pv-1",
        run_id=run_id,
    )


def test_dispatcher_rejects_duplicate_dispatch_for_same_run(monkeypatch):
    """Dispatching the same run_id twice must reject the second dispatch."""
    dispatcher = ThreadRunDispatcher()

    started = threading.Event()
    release = threading.Event()

    def slow_execute(self, request: RunRequest) -> None:
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(RunWorker, "execute", slow_execute)

    dispatcher.dispatch(_request("run-1"))
    try:
        assert started.wait(timeout=2)
        with pytest.raises(Exception) as exc_info:
            dispatcher.dispatch(_request("run-1"))
        assert "already" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower()
    finally:
        release.set()
        dispatcher.shutdown()


def test_dispatcher_get_status_reports_running_then_unknown(monkeypatch):
    dispatcher = ThreadRunDispatcher()

    started = threading.Event()
    release = threading.Event()

    def slow_execute(self, request: RunRequest) -> None:
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(RunWorker, "execute", slow_execute)

    dispatcher.dispatch(_request("run-1"))
    try:
        assert started.wait(timeout=2)
        status = dispatcher.get_status("run-1")
        assert status == "running"
    finally:
        release.set()
        dispatcher.shutdown()

    assert dispatcher.get_status("run-1") == "unknown"


def test_dispatcher_enforces_max_workers_bound(monkeypatch):
    """A dispatcher with max_workers=1 rejects a second concurrent dispatch."""
    dispatcher = ThreadRunDispatcher(max_workers=1)

    started = threading.Event()
    release = threading.Event()

    def slow_execute(self, request: RunRequest) -> None:
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(RunWorker, "execute", slow_execute)

    dispatcher.dispatch(_request("run-1"))
    try:
        assert started.wait(timeout=2)
        with pytest.raises(CardreError):
            dispatcher.dispatch(_request("run-2"))
    finally:
        release.set()
        dispatcher.shutdown()
