"""SQLite pending run-dispatch repository.

Records runs whose async submission has been committed durably but not yet
claimed by a worker. A row is written in the same transaction as run creation;
the worker atomically removes it when it claims the run. Startup reconciliation
drains any rows left by a crash between the DB commit and the in-memory
dispatch, so an async run is never stranded in ``created``/``queued``.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.diagnostics import utc_now_iso


class DispatchRepo:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def enqueue(self, run_id: str) -> None:
        """Record that *run_id* still needs to be claimed by a worker.

        Called inside the same mutation transaction as run creation, so the
        dispatch intent is durable before any in-memory scheduling happens.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO pending_run_dispatches (run_id, created_at) VALUES (?, ?)",
            (run_id, utc_now_iso()),
        )

    def claim(self, run_id: str) -> bool:
        """Atomically remove the pending dispatch for *run_id*.

        Returns whether a pending row existed (i.e. this caller won the claim).
        """
        cursor = self._conn.execute(
            "DELETE FROM pending_run_dispatches WHERE run_id = ?", (run_id,)
        )
        return bool(cursor.rowcount > 0)

    def list_pending(self) -> list[str]:
        """Return run_ids whose dispatch is still pending, oldest first."""
        rows = self._conn.execute(
            "SELECT run_id FROM pending_run_dispatches ORDER BY created_at, run_id"
        ).fetchall()
        return [str(r["run_id"]) for r in rows]

    def remove(self, run_id: str) -> None:
        """Remove the pending dispatch row (used on cancellation of a pre-claim
        run, where no worker will ever claim it)."""
        self._conn.execute(
            "DELETE FROM pending_run_dispatches WHERE run_id = ?", (run_id,)
        )
