"""RecoverStaleRuns — periodically interrupt abandoned running Runs.

A running Run whose heartbeat is old (or absent/malformed) and which has not
been renewed by a worker is abandoned. Previously this recovery only ran as a
side effect of the *next* Run submission (``SubmitRun._sweep_stale``), so an
abandoned Run with no later submission could stay ``running`` indefinitely.

This module is an explicit, periodically invoked recovery trigger. It scans
running Runs for staleness using the injected ``ClockPort`` (no direct
wall-clock read in this path) and hands each stale candidate's *observed*
heartbeat to ``FinalizeRun``, which atomically compare-and-sets the ``interrupted``
transition, appends the ``RUN_STALE`` diagnostic, builds the canonical manifest,
and enqueues the outbox record — all in one transaction.

If the worker renewed the heartbeat (or the Run already terminalized) between
discovery and finalization, the compare-and-set loses and the Run is untouched.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cardre.application.ports.clock import ClockPort
from cardre.domain.run import RunStatus


@dataclass
class StaleRunRecoveryResult:
    run_id: str
    project_id: str
    state: str  # 'interrupted' | 'fresh' | 'error'
    error: str = ""


@dataclass
class StaleRunRecoveryOutcome:
    results: list[StaleRunRecoveryResult] = field(default_factory=list)

    @property
    def interrupted(self) -> int:
        return sum(1 for r in self.results if r.state == "interrupted")


class RecoverStaleRuns:
    """Recovery Module: interrupt stale running Runs across all projects."""

    def __init__(
        self,
        uow_factory: Any,
        project_registry: Any,
        finalize_run_factory: Callable[[str], Any],
        clock: ClockPort,
        stale_heartbeat_seconds: int = 300,
    ) -> None:
        self._uow_factory = uow_factory
        self._project_registry = project_registry
        self._finalize_run_factory = finalize_run_factory
        self._clock = clock
        self._stale_heartbeat_seconds = stale_heartbeat_seconds

    def __call__(self) -> StaleRunRecoveryOutcome:
        outcome = StaleRunRecoveryOutcome()
        # Derive the wall-clock instant from the injected ClockPort only.
        now_ts = _iso_to_ts(self._clock.now_iso())
        for project_id, root in self._project_registry.list_all().items():
            if not (Path(root) / "project.sqlite").exists():
                continue
            try:
                with self._uow_factory.read_only(project_id) as uow:
                    candidates = [
                        (run.run_id, run.heartbeat_at)
                        for run in uow.runs.list_for_plan_version()
                        if run.status == RunStatus.RUNNING.value
                        and run.is_stale(
                            stale_heartbeat_seconds=self._stale_heartbeat_seconds,
                            now_ts=now_ts,
                        )
                    ]
            except Exception as exc:  # noqa: BLE001
                outcome.results.append(StaleRunRecoveryResult(
                    run_id="", project_id=project_id, state="error",
                    error=f"stale scan failed: {exc}",
                ))
                continue
            for run_id, hb in candidates:
                try:
                    from cardre.application.runs.finalize_run import FinalizeDiagnostic

                    self._finalize_run_factory(project_id)(
                        run_id,
                        "interrupted",
                        diagnostic=FinalizeDiagnostic(
                            code="RUN_STALE",
                            message="Run was stale and has been interrupted",
                        ),
                        stale_heartbeat_at=hb,
                    )
                    # Report the actual compare-and-set outcome: the worker may
                    # have renewed the lease (or the run terminalized) between
                    # discovery and finalization, in which case the transition
                    # lost and the run is untouched.
                    with self._uow_factory.read_only(project_id) as uow:
                        run = uow.runs.get(run_id)
                    state = (
                        "interrupted"
                        if run is not None
                        and run.status == RunStatus.INTERRUPTED.value
                        else "fresh"
                    )
                    outcome.results.append(StaleRunRecoveryResult(
                        run_id=run_id, project_id=project_id, state=state,
                    ))
                except Exception as exc:  # noqa: BLE001
                    outcome.results.append(StaleRunRecoveryResult(
                        run_id=run_id, project_id=project_id, state="error",
                        error=str(exc),
                    ))
        return outcome


def _iso_to_ts(iso: str) -> float:
    from datetime import UTC, datetime

    return datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp()


class StaleRunRecoveryWatchdog:
    """Runs ``RecoverStaleRuns`` periodically from a lifecycle-owned thread.

    ``start()`` launches the daemon thread; ``stop()`` signals it and joins the
    thread so shutdown is deterministic. The recovery module's own
    ``ClockPort``-based staleness check means the interval is decoupled from the
    heartbeat-stale threshold (the module re-checks real staleness each pass).
    """

    def __init__(
        self,
        recovery: Callable[[], Any],
        interval_seconds: float,
    ) -> None:
        self._recovery = recovery
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="stale-run-recovery",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._interval * 2, 1.0))
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._recovery()
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).exception(
                    "StaleRunRecoveryWatchdog: recovery pass failed"
                )


__all__ = [
    "RecoverStaleRuns",
    "StaleRunRecoveryOutcome",
    "StaleRunRecoveryResult",
    "StaleRunRecoveryWatchdog",
]
