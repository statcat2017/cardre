"""Dispatch substrate — sync and thread dispatchers for run execution.

Re-exports from ``worker.py`` for convenience.
"""

from __future__ import annotations

from cardre.execution.worker import (
    RunDispatcher,
    RunRequest,
    RunWorker,
    SyncRunDispatcher,
    ThreadRunDispatcher,
    _fail_run_if_running,
)

__all__ = [
    "RunDispatcher",
    "RunRequest",
    "RunWorker",
    "SyncRunDispatcher",
    "ThreadRunDispatcher",
    "_fail_run_if_running",
]
