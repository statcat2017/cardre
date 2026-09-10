"""P2 — watchdog restart/stop lifecycle regression tests.

Both ``HeartbeatWatchdog`` and ``StaleRunRecoveryWatchdog`` must be
restart-safe:

* ``start -> observe -> stop -> start`` runs the callback again;
* ``start`` must not spawn a second thread while an old one is alive;
* ``stop`` must not forget a thread that remains alive after a timed join —
  the reference is only cleared once the thread has terminated.
"""
from __future__ import annotations

import threading
import time

from cardre.application.execution.heartbeat import HeartbeatWatchdog
from cardre.application.runs.recover_stale_runs import StaleRunRecoveryWatchdog


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ---------------------------------------------------------------------------
# HeartbeatWatchdog
# ---------------------------------------------------------------------------


def test_heartbeat_watchdog_restart_runs_again():
    calls: list[int] = []
    wd = HeartbeatWatchdog(lambda: calls.append(1), "run-1", interval_seconds=0.01)
    wd.start()
    assert _wait_for(lambda: len(calls) >= 1), "watchdog must run the heartbeat"
    wd.stop()
    count_after_stop = len(calls)
    time.sleep(0.05)
    assert len(calls) == count_after_stop, "watchdog must not run after stop"

    wd.start()
    assert _wait_for(lambda: len(calls) > count_after_stop), (
        "restarted watchdog must run the heartbeat again"
    )
    wd.stop()


def test_heartbeat_watchdog_start_does_not_create_second_thread():
    wd = HeartbeatWatchdog(lambda: None, "run-1", interval_seconds=0.01)
    wd.start()
    first = wd._thread
    assert first is not None and first.is_alive()
    wd.start()
    assert wd._thread is first, "start must not create a second thread while alive"
    wd.stop()


def test_heartbeat_watchdog_stop_keeps_alive_thread_reference():
    entered = threading.Event()
    release = threading.Event()

    def blocking_factory():
        entered.set()
        release.wait(timeout=5)
        raise RuntimeError("released")

    wd = HeartbeatWatchdog(blocking_factory, "run-1", interval_seconds=0.01)
    wd.start()
    assert entered.wait(timeout=5), "thread must enter the blocking factory"
    thread = wd._thread
    assert thread is not None and thread.is_alive()

    wd.stop()  # join times out: thread is blocked in the factory
    assert wd._thread is thread, "stop must not forget a still-alive thread"
    assert thread.is_alive()

    wd.start()  # must not spawn a second thread while the old one is alive
    assert wd._thread is thread, "start must not create a second thread"

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()

    wd.start()  # old thread is dead: a fresh thread is created
    assert wd._thread is not thread
    wd.stop()


# ---------------------------------------------------------------------------
# StaleRunRecoveryWatchdog
# ---------------------------------------------------------------------------


def test_stale_watchdog_restart_runs_again():
    calls: list[int] = []
    wd = StaleRunRecoveryWatchdog(lambda: calls.append(1), interval_seconds=0.01)
    wd.start()
    assert _wait_for(lambda: len(calls) >= 1), "watchdog must run the recovery"
    wd.stop()
    count_after_stop = len(calls)
    time.sleep(0.05)
    assert len(calls) == count_after_stop, "watchdog must not run after stop"

    wd.start()
    assert _wait_for(lambda: len(calls) > count_after_stop), (
        "restarted watchdog must run the recovery again"
    )
    wd.stop()


def test_stale_watchdog_start_does_not_create_second_thread():
    wd = StaleRunRecoveryWatchdog(lambda: None, interval_seconds=0.01)
    wd.start()
    first = wd._thread
    assert first is not None and first.is_alive()
    wd.start()
    assert wd._thread is first, "start must not create a second thread while alive"
    wd.stop()


def test_stale_watchdog_stop_keeps_alive_thread_reference():
    entered = threading.Event()
    release = threading.Event()

    def blocking_recovery():
        entered.set()
        release.wait(timeout=5)

    wd = StaleRunRecoveryWatchdog(blocking_recovery, interval_seconds=0.01)
    wd.start()
    assert entered.wait(timeout=5), "thread must enter the blocking recovery"
    thread = wd._thread
    assert thread is not None and thread.is_alive()

    wd.stop()  # join times out: thread is blocked in the recovery callable
    assert wd._thread is thread, "stop must not forget a still-alive thread"
    assert thread.is_alive()

    wd.start()  # must not spawn a second thread while the old one is alive
    assert wd._thread is thread, "start must not create a second thread"

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()

    wd.start()  # old thread is dead: a fresh thread is created
    assert wd._thread is not thread
    wd.stop()
