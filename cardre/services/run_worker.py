"""Run worker and dispatcher — the single seam for background run execution.

RunService delegates async execution to a :class:`RunDispatcher` rather
than constructing ``threading.Thread`` directly. This centralises:

* worker **naming** (``cardre-run-{run_id_prefix}``);
* **exception handling** and diagnostic recording;
* **final status** handling (fail-if-running);
* a clear seam for future process/queue-based execution.

The default :class:`ThreadRunDispatcher` preserves the previous
behaviour: a fire-and-forget background ``threading.Thread``. Tests use
:class:`SyncRunDispatcher` to run the worker inline, or inject a fake
dispatcher to assert dispatch behaviour.

This module owns *how* a run is dispatched, not *what* it executes. The
worker body (:class:`RunWorker`) calls into :mod:`cardre.executor` and
records diagnostics on failure, replacing the duplicated worker bodies
that previously lived in ``RunService._run_async_worker`` and
``run_orchestrator.dispatch_run_async``.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from cardre.audit import utc_now_iso
from cardre.store import ProjectStore

logger = logging.getLogger(__name__)

# Diagnostic codes recorded by the worker / dispatcher.
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
    * final-status cleanup (``fail_run_if_running``).

    It delegates actual step execution to
    :func:`cardre.services.run_orchestrator.execute_run`, which
    constructs the executor. This keeps the sync and async paths
    sharing one execution entrypoint.

    It deliberately does *not* decide dispatch strategy (thread / process /
    queue) — that is the dispatcher's job.
    """

    def execute(self, request: RunRequest) -> None:
        store = ProjectStore(request.project_path)
        try:
            store.run_heartbeat(request.run_id)
            self._invoke_executor(store, request)
        except Exception:
            self._record_failure(store, request, sys.exc_info())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _invoke_executor(store: ProjectStore, request: RunRequest) -> None:
        from cardre.services.run_orchestrator import execute_run

        execute_run(
            store=store,
            plan_version_id=request.plan_version_id,
            run_id=request.run_id,
            run_scope=request.run_scope,
            branch_id=request.branch_id,
            target_step_id=request.target_step_id,
            force=request.force,
        )

    @staticmethod
    def _record_failure(
        store: ProjectStore,
        request: RunRequest,
        exc_info: tuple,
    ) -> None:
        exc_type, exc_value, _ = exc_info
        tb = traceback.format_exc()
        logger.error(
            "RunWorker(%s) failed: %s", request.run_id, tb,
        )
        diag = {
            "code": WORKER_FAILED_CODE,
            "message": f"{exc_type.__name__ if exc_type else 'Exception'}: {exc_value}",
            "severity": "error",
            "category": "execution",
            "exception_type": exc_type.__name__ if exc_type else "Exception",
            "run_id": request.run_id,
            "plan_version_id": request.plan_version_id,
            "branch_id": request.branch_id,
            "traceback": tb,
            "created_at": utc_now_iso(),
        }
        store.append_run_diagnostic(request.run_id, diag)
        _fail_run_if_running(store, request.run_id)


def _fail_run_if_running(store: ProjectStore, run_id: str) -> None:
    """Mark a run ``failed`` iff it is still ``running``.

    Last-resort cleanup: if the run was not finalised by the executor
    (e.g. an exception escaped before ``RunLifecycle`` could finalise),
    ensure it is not left ``running``. Never raises.
    """
    try:
        run = store.get_run(run_id)
        if run and run.get("status") == "running":
            store.finish_run(run_id, "failed")
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("_fail_run_if_running failed for run %s: %s", run_id, e)


# ---------------------------------------------------------------------------
# RunDispatcher — the seam for *how* a run is dispatched
# ---------------------------------------------------------------------------


@runtime_checkable
class RunDispatcher(Protocol):
    """Dispatch a :class:`RunRequest` for background execution.

    Implementations decide the execution substrate (thread, process,
    queue, inline). They must:

    * raise :class:`cardre.errors.CardreError` (code
      ``RUN_DISPATCH_FAILED``) if dispatch startup fails, *after*
      recording a diagnostic;
    * never let worker exceptions escape — the worker owns those.
    """

    def dispatch(self, request: RunRequest) -> None:
        ...


# ---------------------------------------------------------------------------
# ThreadRunDispatcher — default, preserves current thread-backed behaviour
# ---------------------------------------------------------------------------


class ThreadRunDispatcher:
    """Dispatch a run on a fire-and-forget background thread.

    This preserves the previous behaviour exactly: a non-daemon
    ``threading.Thread`` is started and not tracked. The worker body is
    :class:`RunWorker`, so naming, exception handling, diagnostics, and
    final-status cleanup are centralised there.

    The thread is named ``cardre-run-{run_id_prefix}`` so it is
    identifiable in thread dumps and logs.
    """

    def __init__(self, worker: RunWorker | None = None) -> None:
        self._worker = worker or RunWorker()

    def dispatch(self, request: RunRequest) -> None:
        from cardre.errors import CardreError

        try:
            thread = threading.Thread(
                target=self._worker.execute,
                args=(request,),
                name=request.worker_name(),
            )
            thread.start()
        except Exception as exc:
            # Dispatch startup failed: record a diagnostic so the failure
            # is debuggable, then surface a typed error. The run was
            # already created in 'running' state by RunService; mark it
            # failed here so it is not left dangling.
            self._record_dispatch_failure(request, exc)
            raise CardreError(
                f"Failed to start background run thread: {exc}",
                code=DISPATCH_FAILED_CODE,
                context={
                    "plan_version_id": request.plan_version_id,
                    "run_id": request.run_id,
                    "run_scope": request.run_scope,
                },
            ) from exc

    @staticmethod
    def _record_dispatch_failure(request: RunRequest, exc: Exception) -> None:
        try:
            store = ProjectStore(request.project_path)
            store.append_run_diagnostic(request.run_id, {
                "code": DISPATCH_FAILED_CODE,
                "message": f"Failed to start background worker: {exc}",
                "severity": "error",
                "category": "lifecycle",
                "exception_type": type(exc).__name__,
                "run_id": request.run_id,
                "plan_version_id": request.plan_version_id,
                "branch_id": request.branch_id,
                "created_at": utc_now_iso(),
            })
            _fail_run_if_running(store, request.run_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to record dispatch failure diagnostic for run %s",
                request.run_id,
            )


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
