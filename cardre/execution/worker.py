"""Run worker and dispatcher — the single seam for background run execution.

RunCoordinator delegates async execution to a :class:`RunDispatcher` rather
than constructing ``threading.Thread`` directly. This centralises:

* worker **naming** (``cardre-run-{run_id_prefix}``);
* **exception capture** — the dispatcher raises ``CardreError`` on startup
  failure; the coordinator writes diagnostic and terminal state through the
  lifecycle seam.

The default :class:`ThreadRunDispatcher` preserves the previous
behaviour: a fire-and-forget background ``threading.Thread``. Tests use
:class:`SyncRunDispatcher` to run the worker inline, or inject a fake
dispatcher to assert dispatch behaviour.

This module owns *how* a run is dispatched, not *what* it executes.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from cardre.domain.diagnostics import utc_now_iso
from cardre.store.db import ProjectStore

logger = logging.getLogger(__name__)

WORKER_FAILED_CODE = "RUN_WORKER_FAILED"
DISPATCH_FAILED_CODE = "RUN_DISPATCH_FAILED"


# ---------------------------------------------------------------------------
# RunRequest — the immutable description of work to dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunRequest:
    """Immutable description of a run to execute in the background."""

    project_path: str
    plan_version_id: str
    run_id: str
    run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan"
    branch_id: str | None = None
    target_step_id: str | None = None
    force: bool = False

    def worker_name(self) -> str:
        """Deterministic, identifiable thread name for this run."""
        return f"cardre-run-{self.run_id[:8]}"


# ---------------------------------------------------------------------------
# RunWorker — the single body that executes a run
# ---------------------------------------------------------------------------


class RunWorker:
    """Execute a single run, recording diagnostics on failure.

    This is the one place where a run's background body lives. It owns:

    * the initial heartbeat;
    * exception capture and diagnostic recording (``RUN_WORKER_FAILED``);
    * finalisation through the lifecycle seam.

    It delegates actual step execution to
    :meth:`RunCoordinator.execute_created_run`, which constructs the
    executor. This keeps the sync and async paths sharing one execution
    entrypoint.
    """

    def execute(self, request: RunRequest) -> None:
        store = ProjectStore(request.project_path)
        store.open()
        try:
            from cardre.store.run_repo import RunRepository
            RunRepository(store).heartbeat(request.run_id)
            self._invoke_executor(store, request)
        except Exception:
            self._record_failure(store, request, sys.exc_info())
        finally:
            store.close()

    @staticmethod
    def _invoke_executor(store: ProjectStore, request: RunRequest) -> None:
        from cardre.services.run_coordinator import RunCoordinator

        RunCoordinator(store).execute_created_run(request.run_id)

    @staticmethod
    def _record_failure(
        store: ProjectStore,
        request: RunRequest,
        exc_info: tuple[Any, ...],
    ) -> None:
        from cardre.domain.run import RunStatus
        from cardre.execution.run_lifecycle import RunLifecycle

        exc_type, exc_value, _ = exc_info
        tb = traceback.format_exc()
        logger.error("RunWorker(%s) failed: %s", request.run_id, tb)
        diagnostic: dict[str, Any] = {
            "code": WORKER_FAILED_CODE,
            "message": f"{exc_type.__name__ if exc_type else 'Exception'}: {exc_value}",
            "severity": "error",
            "run_id": request.run_id,
            "plan_version_id": request.plan_version_id,
            "branch_id": request.branch_id,
            "traceback": tb,
            "created_at": utc_now_iso(),
        }
        try:
            RunLifecycle.start(
                store,
                request.plan_version_id,
                request.run_id,
                execution_mode=request.run_scope,
                branch_id=request.branch_id,
                target_step_id=request.target_step_id,
            ).finalise(RunStatus.FAILED, diagnostic=diagnostic)
        except Exception:
            logger.exception("Run worker failure finalisation failed for run %s", request.run_id)


# ---------------------------------------------------------------------------
# RunDispatcher — the seam for *how* a run is dispatched
# ---------------------------------------------------------------------------


@runtime_checkable
class RunDispatcher(Protocol):
    """Dispatch a :class:`RunRequest` for background execution.

    Implementations decide the execution substrate (thread, process,
    queue, inline). They must:

    * raise :class:`cardre.domain.errors.CardreError` (code
      ``RUN_DISPATCH_FAILED``) if dispatch startup fails;
    * never let worker exceptions escape — the worker owns those.
    """

    def dispatch(self, request: RunRequest) -> None:
        ...


# ---------------------------------------------------------------------------
# ThreadRunDispatcher — default, preserves current thread-backed behaviour
# ---------------------------------------------------------------------------


class ThreadRunDispatcher:
    """Dispatch a run on a tracked, bounded background thread.

    The thread is named ``cardre-run-{run_id_prefix}`` so it is
    identifiable in thread dumps and logs. Dispatched runs are tracked
    in a locked registry so that:

    * duplicate dispatch for the same ``run_id`` is rejected;
    * ``get_status(run_id)`` reports ``running`` or ``unknown``;
    * a ``max_workers`` bound limits concurrent thread creation.
    """

    def __init__(
        self,
        worker: RunWorker | None = None,
        max_workers: int = 1,
    ) -> None:
        self._worker = worker or RunWorker()
        self._max_workers = max_workers
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def dispatch(self, request: RunRequest) -> None:
        from cardre.domain.errors import CardreError

        try:
            with self._lock:
                if request.run_id in self._threads:
                    raise CardreError(
                        f"Run {request.run_id!r} is already dispatched; "
                        f"duplicate dispatch is rejected.",
                        code=DISPATCH_FAILED_CODE,
                        context={
                            "plan_version_id": request.plan_version_id,
                            "run_id": request.run_id,
                            "run_scope": request.run_scope,
                        },
                    )
                if len(self._threads) >= self._max_workers:
                    raise CardreError(
                        f"Dispatcher is at max_workers={self._max_workers} bound; "
                        f"cannot dispatch run {request.run_id!r}.",
                        code=DISPATCH_FAILED_CODE,
                        context={
                            "plan_version_id": request.plan_version_id,
                            "run_id": request.run_id,
                            "run_scope": request.run_scope,
                            "max_workers": self._max_workers,
                        },
                    )
                thread = threading.Thread(
                    target=self._run,
                    args=(request,),
                    name=request.worker_name(),
                )
                self._threads[request.run_id] = thread
            thread.start()
        except CardreError:
            raise
        except Exception as exc:
            with self._lock:
                self._threads.pop(request.run_id, None)
            raise CardreError(
                f"Failed to start background run thread: {exc}",
                code=DISPATCH_FAILED_CODE,
                context={
                    "plan_version_id": request.plan_version_id,
                    "run_id": request.run_id,
                    "run_scope": request.run_scope,
                },
            ) from exc

    def _run(self, request: RunRequest) -> None:
        try:
            self._worker.execute(request)
        finally:
            with self._lock:
                self._threads.pop(request.run_id, None)

    def get_status(self, run_id: str) -> str:
        """Return ``"running"`` if the run is still dispatched, else ``"unknown"``."""
        with self._lock:
            thread = self._threads.get(run_id)
        if thread is None:
            return "unknown"
        if thread.is_alive():
            return "running"
        with self._lock:
            self._threads.pop(run_id, None)
        return "unknown"

    def shutdown(self) -> None:
        """Wait for all dispatched threads to finish (best-effort)."""
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=30)


# ---------------------------------------------------------------------------
# SyncRunDispatcher — runs the worker inline (for tests and the sync path)
# ---------------------------------------------------------------------------


class SyncRunDispatcher:
    """Run the worker in the current thread, blocking until it finishes.

    Used by tests that want deterministic execution without threads, and
    available as the dispatcher backing ``sync=True``. Exceptions from
    the worker are already captured by :class:`RunWorker`; this dispatcher
    does not re-raise them.
    """

    def __init__(self, worker: RunWorker | None = None) -> None:
        self._worker = worker or RunWorker()

    def dispatch(self, request: RunRequest) -> None:
        self._worker.execute(request)


__all__ = [
    "RunDispatcher",
    "RunRequest",
    "RunWorker",
    "SyncRunDispatcher",
    "ThreadRunDispatcher",
]
