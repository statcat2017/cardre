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

    def resolve(self, node_type: str) -> Any:
        """Resolve a node type name to its node class."""
        ...

    def list_types(self) -> list[str]:
        """Return the node type names in the catalogue."""
        ...

    def instantiate(self, node_type: str) -> Any:
        """Instantiate a node type name into a node instance."""
        ...

    def has(self, node_type: str) -> bool:
        """Return whether a node type is registered."""
        ...
