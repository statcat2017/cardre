"""Target-definition validation — single source of truth.

Validates the shape of a binary-target definition (target column, good/bad/
indeterminate value sets) with the exact semantics execution consumes. Both
the ``DefineModellingMetadataNode`` validator and the canonical commit-
readiness gate call this, so the rules cannot drift apart.

Execution consumes each value-list member verbatim (``str(v)`` without
stripping), so a blank or null member would become a spurious declared
category. Accordingly these checks reject null/blank members and perform
overlap checks on the exact representation runtime uses.

An *absent* optional key (e.g. no ``indeterminate_values``) is valid; an
*explicit null* is not — it would be iterated at runtime and raise.
"""

from __future__ import annotations

from typing import Any

_OPTIONAL_TARGET_LIST_KEYS = ("good_values", "bad_values", "indeterminate_values")


def normalize_target_values(values: Any) -> list[str]:
    """Return the exact string representation of each non-blank, non-null
    member (duplicates collapse via the caller's set)."""
    if not isinstance(values, list):
        return []
    return [str(v) for v in values if v is not None and str(v).strip()]


def target_list_errors(params: dict[str, Any], key: str) -> list[str]:
    """Reject an explicit null or a blank member in a target value list.

    ``key not in params`` (absent) is valid; ``params[key] is None`` is not —
    runtime iterates the value, so an explicit null would crash execution.
    """
    if key not in params:
        return []
    values = params[key]
    if not isinstance(values, list):
        return [f"{key} must be a list"]
    errors: list[str] = []
    for i, value in enumerate(values):
        if value is None:
            errors.append(f"{key}[{i}] must not be null")
        elif isinstance(value, str) and not value.strip():
            errors.append(f"{key}[{i}] must not be blank")
    return errors


def validate_target_definition(params: dict[str, Any]) -> list[str]:
    """Data-independent validation of a binary-target definition.

    Does not require the dataset: it validates the shape of the declared
    target column and good/bad/indeterminate value sets so a semantically
    contradictory definition cannot be committed as immutable.
    """
    errors: list[str] = []

    target_column = params.get("target_column")
    if not isinstance(target_column, str) or not target_column.strip():
        errors.append("target_column must be non-whitespace text")

    for key in _OPTIONAL_TARGET_LIST_KEYS:
        errors.extend(target_list_errors(params, key))

    good_values = normalize_target_values(params.get("good_values"))
    bad_values = normalize_target_values(params.get("bad_values"))
    indeterminate_values = normalize_target_values(params.get("indeterminate_values"))

    if not good_values:
        errors.append("good_values must contain at least one non-blank value")
    if not bad_values:
        errors.append("bad_values must contain at least one non-blank value")

    good_set = set(good_values)
    bad_set = set(bad_values)
    indeterminate_set = set(indeterminate_values)

    overlap_gb = good_set & bad_set
    if overlap_gb:
        errors.append(f"good_values and bad_values must be disjoint; overlap: {sorted(overlap_gb)}")
    overlap_gi = good_set & indeterminate_set
    if overlap_gi:
        errors.append(
            f"good_values and indeterminate_values must be disjoint; overlap: {sorted(overlap_gi)}"
        )
    overlap_bi = bad_set & indeterminate_set
    if overlap_bi:
        errors.append(
            f"bad_values and indeterminate_values must be disjoint; overlap: {sorted(overlap_bi)}"
        )

    return errors


__all__ = [
    "normalize_target_values",
    "target_list_errors",
    "validate_target_definition",
]
