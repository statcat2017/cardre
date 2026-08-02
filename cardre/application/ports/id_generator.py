"""ID generator port — injectable unique-ID source for use cases."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IdGeneratorPort(Protocol):
    """Injectable unique-ID generator.

    Use cases depend on this protocol rather than calling
    ``uuid.uuid4()`` directly, so ID generation is injectable
    for tests and deterministic replay.
    """

    def new_id(self) -> str:
        """Return a new unique identifier string."""
        ...
