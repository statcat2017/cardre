"""Heartbeat — lease renewal for a running run.

The run lease is renewed periodically *during* node execution, not just
between nodes, so a legitimate node that runs longer than the stale threshold
is not terminalized by the stale sweep. ``HeartbeatWatchdog`` runs a daemon
thread that renews the heartbeat until stopped; it is started when a run
claims ``running`` and stopped before finalization.

A persistently failing background heartbeat must not be swallowed forever: a
silently-healthy run on a dead heartbeat write would only be caught later by
the stale sweep. After ``max_consecutive_failures`` consecutive write failures
the watchdog invokes ``on_failure`` (once) and stops, so the caller can make
the failure observable and terminalize the run deterministically. A single
transient failure followed by a success resets the counter and never triggers
``on_failure``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


def heartbeat(uow: object, run_id: str) -> None:
    uow.runs.heartbeat(run_id)  # type: ignore[union-attr]


class HeartbeatWatchdog:
    """Periodically renews a run's lease from a background thread.

    ``interval_seconds`` must be well below the stale threshold so a node
    blocked for the full interval is still renewed before it looks stale.

    ``on_failure`` is invoked from the watchdog thread exactly once when
    ``max_consecutive_failures`` consecutive heartbeat writes have failed; the
    loop then stops so the caller is not repeatedly notified. A successful
    write resets the consecutive-failure counter.
    """

    def __init__(
        self,
        uow_factory: Callable[[], Any],
        run_id: str,
        interval_seconds: float,
        on_failure: Callable[[], None] | None = None,
        max_consecutive_failures: int | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._run_id = run_id
        self._interval = interval_seconds
        self._on_failure = on_failure
        self._max_consecutive_failures = max_consecutive_failures
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self._run_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._interval * 2, 1.0))
            self._thread = None

    def _run(self) -> None:
        consecutive_failures = 0
        while not self._stop.wait(self._interval):
            uow = self._uow_factory()
            try:
                heartbeat(uow, self._run_id)
                uow.commit()
            except Exception:
                uow.rollback()
                consecutive_failures += 1
                if (
                    self._max_consecutive_failures is not None
                    and consecutive_failures >= self._max_consecutive_failures
                ):
                    if self._on_failure is not None:
                        self._on_failure()
                    break
            else:
                consecutive_failures = 0
            finally:
                uow.close()


__all__ = ["HeartbeatWatchdog", "heartbeat"]
