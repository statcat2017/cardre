"""Parameter schema framework for Cardre node types.

Provides the data model and validation helpers for the Node Method &
Parameter Schema Framework. Each NodeType exposes its parameter metadata
through ``parameter_schema()``.

Two-layer validation system:

1. **Schema layer** (``parameter_schema()`` + ``validate_against_schema()``):
   Used at *plan-submission time* (plan_service.py) to validate params
   before a plan is saved. The schema is also the source of truth for
   UI rendering and default merging (``merge_defaults``).

2. **Execution layer** (``NodeType.validate_params()``):
   Used at *run-execution time* (executor.py) as a final check before
   a node runs. The executor calls ``node.validate_params(spec.params)``
   directly. Nodes should NOT re-implement schema constraints here —
   use ``validate_against_schema`` at plan time for schema-level rules.
   Override ``validate_params`` only for cross-param or runtime checks
   that the schema cannot express.

The two layers are NOT redundant: schema validation runs when a plan is
created/edited (UI/API path); execution validation runs just before a
step executes (runtime path). Deferred nodes (boosting, ensembles, etc.)
are guarded at instantiation time so their execution validation is
effectively bypassed without needing to strip the imperative code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParameterConstraint:
    """Validation constraint for a parameter value."""
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    exclusive_min: float | None = None
    exclusive_max: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    enum_values: list[Any] | None = None
    pattern: str | None = None


@dataclass
class ParameterDefinition:
    """Definition of a single parameter for a method option.

    Supported kinds: ``string``, ``integer``, ``float``, ``boolean``,
    ``enum``, ``list``, ``object``.
    """
    name: str
    label: str
    kind: str
    default: Any = None
    required: bool = False
    constraint: ParameterConstraint | None = None
    help_text: str = ""
    group: str = ""


@dataclass
class MethodOption:
    """A method or variant available for a node type."""
    id: str
    label: str
    status: str = "available"
    params: list[ParameterDefinition] = field(default_factory=list)
    description: str = ""


@dataclass
class NodeParameterSchema:
    """Complete parameter schema for a node type.

    If only one method is available, ``default_method`` can be left empty
    and the system uses the first method.
    """
    node_type: str
    node_version: str
    title: str = ""
    methods: list[MethodOption] = field(default_factory=list)
    default_method: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_method(schema: NodeParameterSchema, params: dict) -> MethodOption | None:
    method_id = params.get("method", schema.default_method)
    if not method_id and schema.methods:
        method_id = schema.methods[0].id
    for m in schema.methods:
        if m.id == method_id:
            return m
    return None


def merge_defaults(schema: NodeParameterSchema, params: dict) -> dict:
    """Return a new dict with schema defaults applied for missing keys.

    The ``"method"`` key is used to select which ``MethodOption``'s
    parameter definitions to apply defaults from.

    If the schema has no methods, *params* is returned unchanged.
    """
    if not schema.methods:
        return dict(params)
    method = _find_method(schema, params)
    if method is None:
        return dict(params)
    merged = dict(params)
    if "method" not in merged and schema.methods:
        merged["method"] = method.id
    for pdef in method.params:
        if pdef.name not in merged:
            merged[pdef.name] = pdef.default
    return merged


def validate_against_schema(schema: NodeParameterSchema, params: dict) -> list[str]:
    """Validate *params* against the schema.  Returns a list of error messages.

    If the schema has no methods (the default empty schema), all params pass.
    """
    errors: list[str] = []
    if not schema.methods:
        return errors
    method = _find_method(schema, params)
    if method is None:
        errors.append(f"Unknown method: {params.get('method')!r}")
        return errors

    if method.status != "available":
        errors.append(
            f"Method {method.id!r} is {method.status!r} and cannot be executed"
        )
        return errors

    for pdef in method.params:
        value = params.get(pdef.name, pdef.default)
        _validate_param(pdef, value, errors)
    return errors


def _validate_param(pdef: ParameterDefinition, value: Any, errors: list[str]) -> None:
    label = pdef.label or pdef.name

    if pdef.required and (value is None or (isinstance(value, str) and value == "")):
        errors.append(f"{label} is required")
        return

    if value is None:
        return

    constraint = pdef.constraint
    if constraint is None:
        return

    if pdef.kind == "integer":
        try:
            int_val = int(value)
        except (ValueError, TypeError):
            errors.append(f"{label} must be an integer")
            return
        if constraint.min_value is not None and int_val < constraint.min_value:
            errors.append(f"{label} must be >= {constraint.min_value}")
        if constraint.max_value is not None and int_val > constraint.max_value:
            errors.append(f"{label} must be <= {constraint.max_value}")
        if constraint.exclusive_min is not None and int_val <= constraint.exclusive_min:
            errors.append(f"{label} must be > {constraint.exclusive_min}")
        if constraint.exclusive_max is not None and int_val >= constraint.exclusive_max:
            errors.append(f"{label} must be < {constraint.exclusive_max}")

    elif pdef.kind == "float":
        try:
            float_val = float(value)
        except (ValueError, TypeError):
            errors.append(f"{label} must be a number")
            return
        if constraint.min_value is not None and float_val < constraint.min_value:
            errors.append(f"{label} must be >= {constraint.min_value}")
        if constraint.max_value is not None and float_val > constraint.max_value:
            errors.append(f"{label} must be <= {constraint.max_value}")
        if constraint.exclusive_min is not None and float_val <= constraint.exclusive_min:
            errors.append(f"{label} must be > {constraint.exclusive_min}")
        if constraint.exclusive_max is not None and float_val >= constraint.exclusive_max:
            errors.append(f"{label} must be < {constraint.exclusive_max}")

    elif pdef.kind == "enum":
        if constraint.enum_values is not None and value not in constraint.enum_values:
            errors.append(f"{label} must be one of: {constraint.enum_values}")

    elif pdef.kind == "string":
        if constraint.enum_values is not None and value not in constraint.enum_values:
            errors.append(f"{label} must be one of: {constraint.enum_values}")
            return
        if isinstance(value, str):
            if constraint.min_length is not None and len(value) < constraint.min_length:
                errors.append(f"{label} must be at least {constraint.min_length} characters")
            if constraint.max_length is not None and len(value) > constraint.max_length:
                errors.append(f"{label} must be at most {constraint.max_length} characters")

    elif pdef.kind == "list":
        if not isinstance(value, list):
            errors.append(f"{label} must be a list")
            return
        if constraint.min_items is not None and len(value) < constraint.min_items:
            errors.append(f"{label} must have at least {constraint.min_items} items")
        if constraint.max_items is not None and len(value) > constraint.max_items:
            errors.append(f"{label} must have at most {constraint.max_items} items")

    elif pdef.kind == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{label} must be a boolean")


__all__ = [
    "MethodOption",
    "NodeParameterSchema",
    "ParameterConstraint",
    "ParameterDefinition",
    "merge_defaults",
    "validate_against_schema",
]
