"""Thread-based run dispatcher — spawns a thread per run."""
from __future__ import annotations

import threading
from collections.abc import Callable

from cardre.application.ports.run_dispatcher import RunRequest
from cardre.application.runs.execute_run import ExecuteRunCommand


class ThreadRunDispatcher:
    def __init__(
        self,
        execute_run: Callable[[ExecuteRunCommand], None],
        max_workers: int = 1,
    ) -> None:
        self._execute_run = execute_run
        self._max_workers = max_workers
        self._active: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._shutdown = False

    def dispatch(self, request: RunRequest) -> None:
        if self._shutdown:
            raise RuntimeError("Dispatcher is shut down")
        with self._lock:
            if request.run_id in self._active:
                raise RuntimeError(f"Run {request.run_id} is already dispatched")
            if len(self._active) >= self._max_workers:
                raise RuntimeError(f"Max workers ({self._max_workers}) reached")
            thread = threading.Thread(
                target=self._worker,
                args=(request.run_id,),
                daemon=True,
            )
            self._active[request.run_id] = thread
            thread.start()

    def _worker(self, run_id: str) -> None:
        try:
            self._execute_run(ExecuteRunCommand(run_id=run_id))
        finally:
            with self._lock:
                self._active.pop(run_id, None)

    def get_status(self, run_id: str) -> str:
        with self._lock:
            if run_id in self._active:
                return "running"
        return "completed"

    def shutdown(self) -> None:
        self._shutdown = True
