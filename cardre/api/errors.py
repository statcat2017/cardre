"""Error envelope for the Cardre v2 API.

All error responses follow the shape::

    {
        "detail": {
            "code": "ERROR_CODE",
            "message": "Human-readable description.",
            "context": {}
        }
    }
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from cardre.domain.errors import CardreError

# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------


class ErrorCode(StrEnum):
    GOVERNANCE_DISABLED = "GOVERNANCE_DISABLED"
    PLAN_VERSION_IMMUTABLE = "PLAN_VERSION_IMMUTABLE"
    STORE_VERSION_INCOMPATIBLE = "STORE_VERSION_INCOMPATIBLE"
    RUN_EXECUTION_FAILED = "RUN_EXECUTION_FAILED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    PLAN_VERSION_NOT_FOUND = "PLAN_VERSION_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    STEP_NOT_FOUND = "STEP_NOT_FOUND"
    BRANCH_NOT_FOUND = "BRANCH_NOT_FOUND"
    COMPARISON_NOT_FOUND = "COMPARISON_NOT_FOUND"
    REVIEW_NOT_FOUND = "REVIEW_NOT_FOUND"
    MISSING_PROJECT_ID = "MISSING_PROJECT_ID"
    MISSING_PROJECT_PATH = "MISSING_PROJECT_PATH"
    RAW_PROJECT_PATH_DISABLED = "RAW_PROJECT_PATH_DISABLED"
    CONCURRENT_RUN = "CONCURRENT_RUN"
    STORE_ALREADY_EXISTS = "STORE_ALREADY_EXISTS"
    INVALID_PROJECT_PATH = "INVALID_PROJECT_PATH"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    PLAN_VERSION_NOT_COMMITTED = "PLAN_VERSION_NOT_COMMITTED"
    GOVERNANCE_NOT_ENABLED = "GOVERNANCE_NOT_ENABLED"
    GRAPH_VALIDATION_ERROR = "GRAPH_VALIDATION_ERROR"
    PLAN_CONTAINS_UNAVAILABLE_NODES = "PLAN_CONTAINS_UNAVAILABLE_NODES"
    RUN_NOT_RUNNING = "RUN_NOT_RUNNING"
    RUN_PLAN_VERSION_MISMATCH = "RUN_PLAN_VERSION_MISMATCH"
    MISSING_INPUT_ARTIFACT = "MISSING_INPUT_ARTIFACT"
    PARAMETER_VALIDATION_ERROR = "PARAMETER_VALIDATION_ERROR"
    ARTIFACT_READ_ERROR = "ARTIFACT_READ_ERROR"
    ARTIFACT_WRITE_ERROR = "ARTIFACT_WRITE_ERROR"
    NODE_NOT_AVAILABLE_FOR_LAUNCH = "NODE_NOT_AVAILABLE_FOR_LAUNCH"
    RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH = "RUN_SCOPE_NOT_AVAILABLE_FOR_LAUNCH"
    BRANCH_VALIDATION_ERROR = "BRANCH_VALIDATION_ERROR"
    OPTIONAL_DEPENDENCY_NOT_INSTALLED = "OPTIONAL_DEPENDENCY_NOT_INSTALLED"
    RUN_LIFECYCLE_ERROR = "RUN_LIFECYCLE_ERROR"


# ---------------------------------------------------------------------------
# CardreApiError
# ---------------------------------------------------------------------------


class CardreApiError(Exception):
    """API-level error with a fixed error code and HTTP status."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}


def error_response(
    code: str,
    message: str,
    status_code: int = 400,
    context: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a standardised error JSON response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "code": code,
                "message": message,
                "context": context or {},
            }
        },
    )


async def cardre_error_handler(request: Request, exc: CardreError) -> JSONResponse:
    """Convert a ``CardreError`` to the standard error envelope."""
    return error_response(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        context=exc.context,
    )


async def cardre_api_error_handler(request: Request, exc: CardreApiError) -> JSONResponse:
    """Convert a ``CardreApiError`` to the standard error envelope."""
    return error_response(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        context=exc.context,
    )


__all__ = [
    "ErrorCode",
    "CardreApiError",
    "cardre_api_error_handler",
    "cardre_error_handler",
    "error_response",
]
