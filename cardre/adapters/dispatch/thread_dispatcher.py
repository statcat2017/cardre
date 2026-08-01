"""Thread-based run dispatcher — spawns a thread per run.

Process-owned: one dispatcher instance is created in the composition root and
shared across projects. The injected ``execute_run`` receives the full
``RunRequest`` so it can resolve the correct project-scoped ``ExecuteRun``;
no dispatcher is constructed per HTTP request. ``max_workers`` bounds
concurrency and ``shutdown()`` rejects new work.

Shutdown semantics: ``shutdown()`` requests cooperative cancellation of every
active run (via the optional ``cancel_run`` hook) and then joins the worker
threads. If any worker is still alive after the drain window, the drain is
reported as failed (``drain_failed``) rather than silently abandoning daemon
workers.
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
        cancel_run: Callable[[RunRequest], None] | None = None,
        drain_timeout_seconds: float = 30.0,
    ) -> None:
        self._execute_run = execute_run
        self._cancel_run = cancel_run
        self._max_workers = max_workers
        self._drain_timeout = drain_timeout_seconds
        self._active: dict[str, threading.Thread] = {}
        self._requests: dict[str, RunRequest] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._drain_failed = False

    def dispatch(self, request: RunRequest) -> None:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Dispatcher is shut down")
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
            self._requests[request.run_id] = request
            thread.start()

    def _worker(self, request: RunRequest) -> None:
        try:
            self._execute_run(request)
        finally:
            with self._lock:
                self._active.pop(request.run_id, None)
                self._requests.pop(request.run_id, None)

    def get_status(self, run_id: str) -> str:
        with self._lock:
            if run_id in self._active:
                return "running"
        return "completed"

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def drain_failed(self) -> bool:
        """True if the last shutdown left daemon workers alive."""
        return self._drain_failed

    def shutdown(self) -> None:
        """Reject new work, cooperatively cancel active runs, and drain.

        Cooperative cancellation sets ``cancel_requested`` on each active run
        so its ExecuteRun fence stops it at the next safe point. Workers are
        then joined. If any worker remains alive after the drain window,
        ``drain_failed`` is set — the caller must decide whether to escalate.
        """
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            active = dict(self._active)

        # Request cancellation of every active run so workers stop at their
        # next fence rather than running to completion unboundedly.
        if self._cancel_run is not None:
            for run_id in list(active):
                request = self._requests.get(run_id)
                if request is not None:
                    import contextlib

                    with contextlib.suppress(Exception):
                        self._cancel_run(request)
        for worker in active.values():
            worker.join(timeout=self._drain_timeout)

        with self._lock:
            self._drain_failed = bool(self._active)
