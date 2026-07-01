"""Node parameter schema definitions for Cardre pipeline nodes.

Each node type declares its parameter schema as a ``NodeParameterSchema``
with one or more ``MethodOption`` groups.  The schema is used for UI
rendering and parameter validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParameterConstraint:
    """Constraints on a parameter value."""
    enum_values: list[Any] | None = None
    min_value: float | None = None
    max_value: float | None = None
    exclusive_min: float | None = None
    exclusive_max: float | None = None
    min_items: int | None = None
    max_items: int | None = None
    pattern: str | None = None


@dataclass
class ParameterDefinition:
    """Definition of a single parameter."""
    name: str
    label: str = ""
    kind: str = "string"
    default: Any = None
    required: bool = True
    help_text: str = ""
    constraint: ParameterConstraint | None = None


@dataclass
class MethodOption:
    """A named method with its parameter definitions."""
    id: str
    label: str = ""
    status: str = "available"
    description: str = ""
    params: list[ParameterDefinition] = field(default_factory=list)


@dataclass
class NodeParameterSchema:
    """Full parameter schema for a node type."""
    node_type: str
    node_version: str
    title: str = ""
    default_method: str = ""
    methods: list[MethodOption] = field(default_factory=list)


__all__ = [
    "MethodOption",
    "NodeParameterSchema",
    "ParameterConstraint",
    "ParameterDefinition",
]
