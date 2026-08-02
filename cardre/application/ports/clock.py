"""Clock port — injectable time source for use cases."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ClockPort(Protocol):
    """Injectable time source.

    Use cases depend on this protocol rather than calling
    ``utc_now_iso()`` directly, so time is injectable for tests.
    """

    def now_iso(self) -> str:
        """Return the current UTC time as an ISO-8601 string."""
        ...
