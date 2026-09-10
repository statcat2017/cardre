"""Synchronous run dispatcher — executes run immediately in the calling thread."""
from __future__ import annotations

from collections.abc import Callable

from cardre.application.ports.run_dispatcher import RunRequest
from cardre.application.runs.execute_run import ExecuteRunCommand


class SyncRunDispatcher:
    def __init__(self, execute_run: Callable[[ExecuteRunCommand], None]) -> None:
        self._execute_run = execute_run
        self._dispatched: set[str] = set()
        self._failed: set[str] = set()

    def dispatch(self, request: RunRequest) -> None:
        # A legitimately redispatched run discards its old completion/failure
        # bookkeeping at admission so it reports completed/failed for this
        # attempt rather than stale state.
        self._dispatched.discard(request.run_id)
        self._failed.discard(request.run_id)
        try:
            self._execute_run(ExecuteRunCommand(run_id=request.run_id))
        except Exception:
            self._failed.add(request.run_id)
            raise
        self._dispatched.add(request.run_id)

    def get_status(self, run_id: str) -> str:
        if run_id in self._failed:
            return "failed"
        if run_id in self._dispatched:
            return "completed"
        return "unknown"

    def shutdown(self) -> None:
        pass
