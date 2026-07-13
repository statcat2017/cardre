"""Thread-safe cursor wrapper for serialized SQLite access."""

from __future__ import annotations

import sqlite3
import threading
from typing import Any


class LockedCursor:
    """Cursor wrapper that serializes fetches on the store lock."""

    def __init__(self, lock: threading.RLock, cursor: sqlite3.Cursor) -> None:
        self._lock = lock
        self._cursor = cursor

    def fetchone(self) -> Any:
        with self._lock:
            return self._cursor.fetchone()

    def fetchall(self) -> Any:
        with self._lock:
            return self._cursor.fetchall()

    def fetchmany(self, size: int | None = None) -> Any:
        with self._lock:
            return self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size)

    def close(self) -> None:
        with self._lock:
            self._cursor.close()

    @property
    def rowcount(self) -> int:
        with self._lock:
            return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        with self._lock:
            return self._cursor.lastrowid

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)
