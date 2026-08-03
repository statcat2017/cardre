"""Node catalogue port — injectable node registry for use cases."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NodeCataloguePort(Protocol):
    """Injectable node catalogue.

    Use cases depend on this protocol rather than importing
    ``NodeCatalogue`` directly, so the catalogue is injectable
    and testable.
    """

    def availability(self, node_type: str) -> Any:
        """Return availability info for a node type."""
        ...

    def resolve(self, node_type: str) -> Any:
        """Resolve a node type name to its node class."""
        ...
