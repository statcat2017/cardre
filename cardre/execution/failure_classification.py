"""Classify a step-execution exception into the structured error_entry
dict recorded in RunStep.errors.

Pure mapping — no ProjectStore, no run/step IDs.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.errors import (
    ArtifactReadError,
    ArtifactWriteError,
    CardreError,
    GraphValidationError,
    NodeNotAvailableForLaunch,
    NodeRoleAccessViolation,
    OptionalDependencyNotInstalled,
    PlanContainsUnavailableNodesError,
)

# Order matters: more specific subclasses first.
_CATEGORY_MAP: tuple[tuple[type[CardreError], str], ...] = (
    (GraphValidationError, "GraphValidationError"),
    (PlanContainsUnavailableNodesError, "PlanContainsUnavailableNodesError"),
    (ArtifactReadError, "ArtifactReadError"),
    (ArtifactWriteError, "ArtifactWriteError"),
    (NodeRoleAccessViolation, "NodeRoleAccessViolation"),
    (NodeNotAvailableForLaunch, "NodeNotAvailableForLaunch"),
    (OptionalDependencyNotInstalled, "OptionalDependencyNotInstalled"),
    (CardreError, "CardreError"),
)

_CODE_MAP: dict[str, str] = {
    "GraphValidationError": "GRAPH_VALIDATION_ERROR",
    "PlanContainsUnavailableNodesError": "PLAN_CONTAINS_UNAVAILABLE_NODES",
    "ArtifactReadError": "ARTIFACT_READ_ERROR",
    "ArtifactWriteError": "ARTIFACT_WRITE_ERROR",
    "NodeRoleAccessViolation": "NODE_ROLE_ACCESS_VIOLATION",
    "NodeNotAvailableForLaunch": "NODE_NOT_AVAILABLE_FOR_LAUNCH",
    "OptionalDependencyNotInstalled": "OPTIONAL_DEPENDENCY_NOT_INSTALLED",
    "CardreError": "CARDRE_ERROR",
}

_DEFAULT_CATEGORY = "InternalExecutionError"
_DEFAULT_CODE = "STEP_FAILED"


def classify_step_failure(exc_value: BaseException | None, traceback_str: str) -> dict[str, Any]:
    """Return the error_entry dict for a caught exception.

    Keys: code, message, traceback, category.
    """
    category = _DEFAULT_CATEGORY
    if exc_value is not None:
        for exc_cls, cat in _CATEGORY_MAP:
            if isinstance(exc_value, exc_cls):
                category = cat
                break
    code = _CODE_MAP.get(category, _DEFAULT_CODE)
    exc_type_name = type(exc_value).__name__ if exc_value is not None else "Unknown"
    return {
        "code": code,
        "message": f"{exc_type_name}: {exc_value}",
        "traceback": traceback_str,
        "category": category,
    }


__all__ = ["classify_step_failure"]
