"""Shared diagnostic helpers with no I/O dependencies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

JsonDict = dict[str, Any]


def utc_now_iso() -> str:
    """ISO-8601 timestamp at UTC, second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


__all__ = ["JsonDict", "utc_now_iso"]
