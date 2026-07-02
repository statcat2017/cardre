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

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from cardre.domain.errors import CardreError


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

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
MISSING_PROJECT_PATH = "MISSING_PROJECT_PATH"
CONCURRENT_RUN = "CONCURRENT_RUN"
STORE_ALREADY_EXISTS = "STORE_ALREADY_EXISTS"


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
    "ARTIFACT_NOT_FOUND",
    "BRANCH_NOT_FOUND",
    "COMPARISON_NOT_FOUND",
    "CONCURRENT_RUN",
    "CardreApiError",
    "GOVERNANCE_DISABLED",
    "MISSING_PROJECT_PATH",
    "PLAN_NOT_FOUND",
    "PLAN_VERSION_IMMUTABLE",
    "PLAN_VERSION_NOT_FOUND",
    "PROJECT_NOT_FOUND",
    "REVIEW_NOT_FOUND",
    "RUN_EXECUTION_FAILED",
    "RUN_NOT_FOUND",
    "STEP_NOT_FOUND",
    "STORE_ALREADY_EXISTS",
    "STORE_VERSION_INCOMPATIBLE",
    "error_response",
    "cardre_error_handler",
    "cardre_api_error_handler",
]
