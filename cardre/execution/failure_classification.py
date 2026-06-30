"""Classify a step-execution exception into the structured error_entry
dict recorded in RunStepRecord.errors.

Pure mapping — no ProjectStore, no run/step IDs.
"""
from __future__ import annotations

from typing import Any

from cardre.errors import (
    ArtifactReadError,
    ArtifactWriteError,
    CardreError,
    ContractViolationError,
    GraphValidationError,
    MissingInputArtifactError,
    NodeExecutionError,
    ParameterValidationError,
)
from cardre.execution.validation import LeakageProtectionError, RoleAccessError

# Order matters: more specific subclasses first.
_CATEGORY_MAP: tuple = (
    (GraphValidationError, "GraphValidationError"),
    (MissingInputArtifactError, "MissingInputArtifactError"),
    (ParameterValidationError, "ParameterValidationError"),
    (ArtifactReadError, "ArtifactReadError"),
    (ArtifactWriteError, "ArtifactWriteError"),
    (NodeExecutionError, "NodeExecutionError"),
    (ContractViolationError, "ContractViolationError"),
    (RoleAccessError, "RoleAccessError"),
    (LeakageProtectionError, "LeakageProtectionError"),
    (CardreError, "CardreError"),
)

_CODE_MAP: dict[str, str] = {
    "GraphValidationError": "GRAPH_VALIDATION_ERROR",
    "MissingInputArtifactError": "MISSING_INPUT_ARTIFACT",
    "ParameterValidationError": "PARAMETER_VALIDATION_ERROR",
    "ArtifactReadError": "ARTIFACT_READ_ERROR",
    "ArtifactWriteError": "ARTIFACT_WRITE_ERROR",
    "NodeExecutionError": "NODE_EXECUTION_ERROR",
    "ContractViolationError": "CONTRACT_VIOLATION_ERROR",
    "RoleAccessError": "ROLE_ACCESS_ERROR",
    "LeakageProtectionError": "LEAKAGE_PROTECTION_ERROR",
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
