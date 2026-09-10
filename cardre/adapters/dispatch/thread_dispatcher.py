"""Thread-based run dispatcher — a fixed worker pool with an in-memory queue.

Process-owned: one dispatcher instance is created in the composition root and
shared across projects. The injected ``execute_run`` receives the full
``RunRequest`` so it can resolve the correct project-scoped ``ExecuteRun``;
no dispatcher is constructed per HTTP request.

``max_workers`` bounds *concurrency*: at most that many runs execute at once.
Requests beyond capacity are queued rather than rejected, so durable dispatch
reconciliation can hand off every pending run without stranding any behind a
full pool. ``dispatch()`` raises only on shutdown or on a duplicate run.

Status reporting: ``get_status`` distinguishes ``running`` (active), ``queued``
(admitted but not yet running), ``completed`` (a successful attempt), ``failed``
(a callback that raised), and ``unknown`` (never dispatched). A run that
previously completed and is legitimately redispatched discards its old
completion/failure bookkeeping at admission, so it reports ``queued`` while
waiting, ``running`` while executing, and ``completed`` after a successful
attempt. Bookkeeping is bounded so stale completed/failed state never dominates
redispatch.

Shutdown semantics: ``shutdown()`` stops admitting new work, cooperatively
cancels every active run (via the optional ``cancel_run`` hook), and joins the
worker pool. Any request still queued at shutdown is discarded — its run stays
durably ``created``/``queued`` and is reconciled on the next process start. If
a worker is still alive after the drain window, the drain is reported as
failed (``drain_failed``) rather than silently abandoning daemon workers.
"""

from __future__ import annotations

import queue
import threading
from collections import OrderedDict
from collections.abc import Callable

from cardre.application.ports.run_dispatcher import RunRequest

# Upper bound on remembered completed/failed run IDs. Keeps bookkeeping bounded
# so a long-lived dispatcher never accumulates unbounded state, while still
# reporting recently-finished runs accurately.
_MAX_REMEMBERED = 10_000


class _BoundedSet:
    """A set with a fixed capacity that evicts the oldest entries on overflow.

    Used to bound completed/failed bookkeeping so stale state cannot dominate
    redispatch. Eviction order is insertion order (oldest first).
    """

    def __init__(self, max_size: int) -> None:
        self._max_size = max_size
        self._data: OrderedDict[str, None] = OrderedDict()

    def add(self, run_id: str) -> None:
        self._data.pop(run_id, None)
        self._data[run_id] = None
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def discard(self, run_id: str) -> None:
        self._data.pop(run_id, None)

    def __contains__(self, run_id: str) -> bool:
        return run_id in self._data


class ThreadRunDispatcher:
    def __init__(
        self,
        execute_run: Callable[[RunRequest], None],
        max_workers: int = 1,
        cancel_run: Callable[[RunRequest], None] | None = None,
        drain_timeout_seconds: float = 30.0,
    ) -> None:
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        self._execute_run = execute_run
        self._cancel_run = cancel_run
        self._max_workers = max_workers
        self._drain_timeout = drain_timeout_seconds
        self._queue: queue.Queue[RunRequest | None] = queue.Queue()
        self._active: dict[str, RunRequest] = {}
        self._queued_or_active: set[str] = set()
        self._completed = _BoundedSet(_MAX_REMEMBERED)
        self._failed = _BoundedSet(_MAX_REMEMBERED)
        self._lock = threading.Lock()
        self._shutdown = False
        self._drain_failed = False
        self._workers = [
            threading.Thread(target=self._worker_loop, name=f"run-worker-{i}", daemon=True)
            for i in range(max_workers)
        ]
        for worker in self._workers:
            worker.start()

    def dispatch(self, request: RunRequest) -> None:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("Dispatcher is shut down")
            if request.run_id in self._queued_or_active:
                raise RuntimeError(f"Run {request.run_id} is already dispatched")
            # A legitimately redispatched run discards its old completion or
            # failure bookkeeping at admission so it reports queued/running/
            # completed for this attempt rather than stale completed/failed.
            self._completed.discard(request.run_id)
            self._failed.discard(request.run_id)
            self._queued_or_active.add(request.run_id)
        self._queue.put(request)

    def _worker_loop(self) -> None:
        while True:
            request = self._queue.get()
            if request is None:
                return
            with self._lock:
                if self._shutdown:
                    # Discard queued work at shutdown; the run stays durably
                    # created/queued and is reconciled on the next start.
                    self._queued_or_active.discard(request.run_id)
                    continue
                self._active[request.run_id] = request
            try:
                self._execute_run(request)
            except Exception as exc:  # noqa: BLE001
                # A failing run must never kill the worker: with a pool of one
                # an escaped exception would leave every subsequent queued run
                # unprocessed until restart. Log, mark the run failed, and
                # continue. The run stays durably recoverable via reconcile.
                import logging

                logging.getLogger(__name__).exception(
                    "run worker %s failed: %s", request.run_id, exc,
                )
                with self._lock:
                    self._failed.add(request.run_id)
            else:
                with self._lock:
                    self._completed.add(request.run_id)
            finally:
                with self._lock:
                    self._active.pop(request.run_id, None)
                    self._queued_or_active.discard(request.run_id)

    def get_status(self, run_id: str) -> str:
        with self._lock:
            if run_id in self._active:
                return "running"
            if run_id in self._completed:
                return "completed"
            if run_id in self._failed:
                return "failed"
            if run_id in self._queued_or_active:
                return "queued"
        return "unknown"

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def queued_count(self) -> int:
        with self._lock:
            return len(self._queued_or_active) - len(self._active)

    @property
    def drain_failed(self) -> bool:
        """True if the last shutdown left daemon workers alive."""
        return self._drain_failed

    def shutdown(self) -> None:
        """Stop admitting new work, cooperatively cancel active runs, and drain.

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
                request = active.get(run_id)
                if request is not None:
                    import contextlib

                    with contextlib.suppress(Exception):
                        self._cancel_run(request)

        # Signal workers to exit after they finish current work / skip queued.
        for _ in self._workers:
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout=self._drain_timeout)

        with self._lock:
            self._drain_failed = bool(self._active)
