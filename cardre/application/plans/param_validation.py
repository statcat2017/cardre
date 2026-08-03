"""Step parameter validation — schema + node-level checks against the catalogue.

Shared by the edit and commit use cases so an invalid parameter set cannot be
persisted or committed as immutable. This mirrors the runtime validation the
StepRunner performs, but without executing the node or requiring artifacts.
"""

from __future__ import annotations

from typing import Any

from cardre.nodes.parameters import normalize_node_params


def validate_step_params(
    node_cls: type,
    params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Validate a full parameter set against a resolved node class.

    Normalizes against the node's declared schema (rejecting unknown keys,
    applying defaults/coercion, enforcing constraints), then runs the node's
    ``validate_params`` for cross-field rules.

    Returns ``(normalized_params, errors)``. ``errors`` is empty when valid;
    ``normalized_params`` is the schema-normalized parameter set to persist.
    """
    node = node_cls()
    schema = node.parameter_schema()
    if schema is not None:
        try:
            normalized = normalize_node_params(schema, dict(params))
        except ValueError as exc:
            return dict(params), [str(exc)]
    else:
        normalized = dict(params)

    errors = node.validate_params(normalized)
    return normalized, errors


__all__ = ["validate_step_params"]
