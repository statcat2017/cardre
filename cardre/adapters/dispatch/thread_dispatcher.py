"""Thread-based run dispatcher — spawns a thread per run.

Process-owned: one dispatcher instance is created in the composition root and
shared across projects. The injected ``execute_run`` receives the full
``RunRequest`` so it can resolve the correct project-scoped ``ExecuteRun``;
no dispatcher is constructed per HTTP request. ``max_workers`` bounds
concurrency and ``shutdown()`` rejects new work.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from cardre.application.ports.run_dispatcher import RunRequest


class ThreadRunDispatcher:
    def __init__(
        self,
        execute_run: Callable[[RunRequest], None],
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
                args=(request,),
                daemon=True,
            )
            self._active[request.run_id] = thread
            thread.start()

    def _worker(self, request: RunRequest) -> None:
        try:
            self._execute_run(request)
        finally:
            with self._lock:
                self._active.pop(request.run_id, None)

    def get_status(self, run_id: str) -> str:
        with self._lock:
            if run_id in self._active:
                return "running"
        return "completed"

    def shutdown(self) -> None:
        self._shutdown = True
        with self._lock:
            workers = list(self._active.values())
        for worker in workers:
            worker.join(timeout=30)
