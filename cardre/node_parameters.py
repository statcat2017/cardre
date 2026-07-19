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


def normalize_node_params(
    schema: NodeParameterSchema,
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Normalize raw persisted parameters against a declared schema.

    Coerces types, applies defaults, and enforces constraints for declared
    parameters.  Unknown keys are preserved (not rejected) for backward
    compatibility with saved plans.  Node-local ``validate_params`` should
    only handle cross-field or data-dependent rules after this.
    """
    method_id = raw.get("method", schema.default_method)
    method = next((m for m in schema.methods if m.id == method_id), None)
    if method is None:
        raise ValueError(
            f"Unknown method {method_id!r} for {schema.node_type}; "
            f"available: {[m.id for m in schema.methods]}"
        )

    definitions = {p.name: p for p in method.params}

    result: dict[str, Any] = {}
    for k, v in raw.items():
        if k == "method":
            continue
        if k in definitions:
            value = _coerce(definitions[k].kind, v)
            _validate_constraint(k, value, definitions[k].constraint)
            result[k] = value
        else:
            # Preserve unknown keys for backward compatibility with saved plans.
            result[k] = v

    for name, param in definitions.items():
        if name not in result:
            if param.required and param.default is None:
                raise ValueError(f"Required parameter {name!r} is missing for {schema.node_type}")
            result[name] = param.default

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
            return value.lower() in ("true", "1", "yes")
        return bool(value)
    return value  # "string" or "enum"


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


__all__ = [
    "MethodOption",
    "NodeParameterSchema",
    "ParameterConstraint",
    "ParameterDefinition",
    "normalize_node_params",
]
