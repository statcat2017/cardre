"""Shared diagnostic helpers with no I/O dependencies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

JsonDict = dict[str, Any]


def utc_now_iso() -> str:
    """ISO-8601 timestamp at UTC, second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string back to a datetime."""
    return datetime.fromisoformat(value)


__all__ = ["JsonDict", "parse_iso", "utc_now_iso"]
