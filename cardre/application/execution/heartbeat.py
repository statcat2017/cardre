"""Heartbeat — lease renewal for a running run.

The run lease is renewed periodically *during* node execution, not just
between nodes, so a legitimate node that runs longer than the stale threshold
is not terminalized by the stale sweep. ``HeartbeatWatchdog`` runs a daemon
thread that renews the heartbeat until stopped; it is started when a run
claims ``running`` and stopped before finalization.

Worker-owned heartbeat renewal is generation-fenced: a worker presents the
generation it captured when it claimed the run, and an obsolete worker (whose
generation was bumped by a stale recovery) cannot refresh another generation's
lease.

Persistent background heartbeat failure is terminalized through a
generation-fenced interrupted transition, while generation mismatch makes the
obsolete worker stop without changing the Run.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def heartbeat(uow: object, run_id: str, worker_generation: int | None = None) -> bool:
    """Renew a run's lease.

    When ``worker_generation`` is provided the renewal is ownership-CAS: it
    only fires while the run is still running AND owned by that generation.
    Returns whether the renewal happened. Without a generation the legacy
    direct heartbeat is used (non-worker callers).
    """
    if worker_generation is not None:
        renewed = uow.runs.heartbeat_fenced(run_id, worker_generation)  # type: ignore[union-attr]
        if not renewed:
            from cardre.domain.errors import LeaseLost
            raise LeaseLost(run_id, "heartbeat lease ownership lost")
        return True
    uow.runs.heartbeat(run_id)  # type: ignore[union-attr]
    return True


class HeartbeatWatchdog:
    """Periodically renews a run's lease from a background thread.

    ``interval_seconds`` must be well below the stale threshold so a node
    blocked for the full interval is still renewed before it looks stale.

    When ``worker_generation`` is provided the renewal is generation-fenced.
    When ``max_failed_heartbeats`` and ``finalize_run`` are provided, a worker
    that persistently fails to renew its lease terminalizes the run it owns via
    a generation-fenced interrupted transition (an obsolete worker cannot
    terminalize a run it no longer owns).
    """

    def __init__(
        self,
        uow_factory: Callable[[], Any],
        run_id: str,
        interval_seconds: float,
        worker_generation: int | None = None,
        max_failed_heartbeats: int | None = None,
        finalize_run: Callable[..., Any] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._run_id = run_id
        self._interval = interval_seconds
        self._worker_generation = worker_generation
        self._max_failed_heartbeats = max_failed_heartbeats
        self._finalize_run = finalize_run
        self._consecutive_failures = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._consecutive_failures = 0
            self._thread = threading.Thread(
                target=self._run,
                name=f"heartbeat-{self._run_id}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(self._interval * 2, 1.0))
            if not thread.is_alive():
                with self._lock:
                    if self._thread is thread:
                        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            uow = None
            renewed = False
            lease_lost = False
            try:
                uow = self._uow_factory()
                heartbeat(
                    uow, self._run_id, worker_generation=self._worker_generation,
                )
                uow.commit()
                renewed = True
            except Exception as exc:
                from cardre.domain.errors import LeaseLost

                if isinstance(exc, LeaseLost):
                    lease_lost = True
                elif uow is not None:
                    uow.rollback()
            finally:
                if uow is not None:
                    uow.close()

            if lease_lost:
                break

            if renewed:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1

            if (
                self._max_failed_heartbeats is not None
                and self._consecutive_failures >= self._max_failed_heartbeats
                and self._finalize_run is not None
            ):
                if self._terminalize():
                    break

    def _terminalize(self) -> bool:
        """Attempt to terminalize the run as ``interrupted``.

        Returns ``True`` when the run is terminal (either this call finalised
        it, or it was already finalised / the lease was lost to another owner),
        in which case the watchdog stops. Returns ``False`` on any other
        finalization failure so the watchdog keeps retrying on subsequent
        intervals rather than silently abandoning the run.
        """
        from cardre.application.runs.finalize_run import (
            FinalizeDiagnostic,
            RunAlreadyFinalised,
        )
        from cardre.domain.errors import LeaseLost

        try:
            self._finalize_run(
                self._run_id,
                "interrupted",
                diagnostic=FinalizeDiagnostic(
                    code="RUN_HEARTBEAT_FAILED",
                    message="Worker heartbeat renewal failed repeatedly",
                ),
                worker_generation=self._worker_generation,
            )
            return True
        except (RunAlreadyFinalised, LeaseLost):
            # The run was already terminalized by another owner, or this
            # worker lost its lease: a benign lost race, treat as a successful
            # stop.
            return True
        except Exception:
            # Any other finalization failure: log it and keep retrying on
            # subsequent intervals rather than silently abandoning the run.
            logger.exception(
                "heartbeat watchdog failed to terminalize run %s; will retry",
                self._run_id,
            )
            return False


__all__ = ["HeartbeatWatchdog", "heartbeat"]
