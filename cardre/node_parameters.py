"""Node parameter schema definitions for Cardre pipeline nodes.

Each node type declares its parameter schema as a ``NodeParameterSchema``
with one or more ``MethodOption`` groups.  The schema is used for UI
rendering and parameter validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_VALID_BOOLEAN_STRINGS = frozenset({"true", "1", "yes", "false", "0", "no"})


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


def normalize_node_params(
    schema: NodeParameterSchema,
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Normalize raw persisted parameters against a declared schema.

    Selects the declared method, coerces types, applies defaults through
    coercion and constraint validation, enforces all constraints, and
    rejects unknown keys.  Node-local ``validate_params`` should only
    handle cross-field or data-dependent rules after this.
    """
    if schema.default_method:
        method_id = raw.get("method", schema.default_method)
    elif len(schema.methods) == 1:
        method_id = raw.get("method", schema.methods[0].id)
    else:
        method_id = raw.get("method", "")

    method = next((m for m in schema.methods if m.id == method_id), None)
    if method is None:
        raise ValueError(
            f"Unknown method {method_id!r} for {schema.node_type}; "
            f"available: {[m.id for m in schema.methods]}"
        )

    definitions = {p.name: p for p in method.params}
    defined_names = set(definitions) | {"method"}

    result: dict[str, Any] = {}

    # Reject unknown keys first — prevents silent typos.
    for k in raw:
        if k not in defined_names:
            raise ValueError(
                f"Unknown parameter {k!r} for {schema.node_type} method {method_id!r}"
            )

    # Process declared parameters (including method).
    if "method" in raw:
        result["method"] = raw["method"]

    for name, param in definitions.items():
        value = raw.get(name, param.default)

        if value is not None:
            value = _coerce(param.kind, value)
            _validate_constraint(name, value, param.constraint)
        elif param.required:
            raise ValueError(
                f"Required parameter {name!r} is missing for "
                f"{schema.node_type} method {method_id!r}"
            )

        result[name] = value

    return result


def _coerce(kind: str, value: Any) -> Any:
    if value is None:
        return None
    if kind == "integer":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered not in _VALID_BOOLEAN_STRINGS:
                raise ValueError(f"Cannot coerce {value!r} to boolean")
            return lowered in ("true", "1", "yes")
        return bool(value)
    return value


def _validate_constraint(name: str, value: Any, constraint: ParameterConstraint | None) -> None:
    if constraint is None or value is None:
        return
    if constraint.enum_values is not None and value not in constraint.enum_values:
        raise ValueError(
            f"Parameter {name!r}: {value!r} is not one of {constraint.enum_values}"
        )
    if isinstance(value, (int, float)):
        if constraint.min_value is not None and value < constraint.min_value:
            raise ValueError(f"Parameter {name!r}: {value} < min_value={constraint.min_value}")
        if constraint.max_value is not None and value > constraint.max_value:
            raise ValueError(f"Parameter {name!r}: {value} > max_value={constraint.max_value}")
        if constraint.exclusive_min is not None and value <= constraint.exclusive_min:
            raise ValueError(f"Parameter {name!r}: {value} <= exclusive_min={constraint.exclusive_min}")
        if constraint.exclusive_max is not None and value >= constraint.exclusive_max:
            raise ValueError(f"Parameter {name!r}: {value} >= exclusive_max={constraint.exclusive_max}")
    if isinstance(value, (list, tuple)):
        if constraint.min_items is not None and len(value) < constraint.min_items:
            raise ValueError(f"Parameter {name!r}: length {len(value)} < min_items={constraint.min_items}")
        if constraint.max_items is not None and len(value) > constraint.max_items:
            raise ValueError(f"Parameter {name!r}: length {len(value)} > max_items={constraint.max_items}")
    if constraint.pattern is not None and isinstance(value, str):
        if not re.search(constraint.pattern, value):
            raise ValueError(f"Parameter {name!r}: {value!r} does not match pattern {constraint.pattern!r}")


__all__ = [
    "MethodOption",
    "NodeParameterSchema",
    "ParameterConstraint",
    "ParameterDefinition",
    "normalize_node_params",
]
