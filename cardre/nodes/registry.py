"""Backward-compat shim — replaced by ``cardre/bootstrap/node_catalogue.py``.

This file will be removed in Batch 05.  New code must use
``NodeCatalogue`` from ``cardre.bootstrap.node_catalogue``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cardre.nodes.contracts import NodeType


@dataclass(frozen=True)
class _NodeAvailability:
    available: bool = False
    tier: str = "unknown"
    disabled_reason: str | None = None
    missing_optional_dependencies: list[str] = field(default_factory=list)


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, type[NodeType]] = {}
        self._available: dict[str, Any] = {}

    def register(self, cls: type[NodeType]) -> type[NodeType]:
        node_type = getattr(cls, "node_type", None)
        if node_type is None:
            raise ValueError(f"{cls.__name__} must define node_type")
        self._nodes[node_type] = cls
        return cls

    def resolve(self, node_type: str) -> type[NodeType]:
        cls = self._nodes.get(node_type)
        if cls is None:
            raise KeyError(f"Unknown node type {node_type!r}")
        return cls

    def has(self, node_type: str) -> bool:
        return node_type in self._nodes

    def list_types(self) -> list[str]:
        return list(self._nodes.keys())

    def availability(self, node_type: str) -> Any:
        return _NodeAvailability(available=False, tier="unknown", disabled_reason="Shim stub — use NodeCatalogue")

    def is_available(self, node_type: str) -> bool:
        return False

    def instantiate(self, node_type: str) -> NodeType:
        raise RuntimeError("NodeRegistry stub — use NodeCatalogue")

    @classmethod
    def with_defaults(cls) -> NodeRegistry:
        return cls()

    def list_launch_nodes(self) -> list[str]:
        return []

    def list_deferred_nodes(self) -> list[str]:
        return []

    @property
    def catalogue(self) -> Any:
        raise RuntimeError("NodeRegistry stub — use NodeCatalogue")
