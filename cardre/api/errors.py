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

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from cardre.domain.errors import CardreError, ErrorCode

logger = logging.getLogger(__name__)

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
    """Convert a ``CardreError`` to the standard error envelope via the map."""
    return await cardre_api_error_handler(request, translate_domain_error(exc))


async def cardre_api_error_handler(request: Request, exc: CardreApiError) -> JSONResponse:
    """Convert a ``CardreApiError`` to the standard error envelope."""
    return error_response(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        context=exc.context,
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle an unexpected exception: log the traceback, return a structured 500.

    Domain/API errors are translated elsewhere; this is the single catch-all for
    anything that reaches the boundary untyped. The response uses the public
    ``INTERNAL_SERVER_ERROR`` code and never
    leaks the exception message or traceback to the client.
    """
    logger.exception("Unhandled exception serving %s %s", request.method, request.url.path)
    return error_response(
        code=ErrorCode.INTERNAL_SERVER_ERROR,
        message="An unexpected internal error occurred.",
        status_code=500,
    )


# ---------------------------------------------------------------------------
# Domain error translation
# ---------------------------------------------------------------------------
# The map is the sole source of HTTP status (and any code translation) for a
# mapped code: per-call ``status_code=`` on a mapped domain error is ignored,
# so one code always maps to exactly one status. Unmapped codes pass through
# with their domain code/status. This is the single home for the per-route
# try/except ladders that used to live in every route file.

_DOMAIN_ERROR_MAP: dict[ErrorCode, tuple[ErrorCode, int]] = {
    ErrorCode.PLAN_VERSION_NOT_FOUND: (ErrorCode.PLAN_VERSION_NOT_FOUND, 404),
    ErrorCode.PLAN_VERSION_ALREADY_COMMITTED: (ErrorCode.PLAN_VERSION_IMMUTABLE, 409),
    ErrorCode.PLAN_VERSION_NOT_COMMITTED: (ErrorCode.PLAN_VERSION_IMMUTABLE, 409),
    ErrorCode.CONCURRENT_RUN: (ErrorCode.CONCURRENT_RUN, 409),
    ErrorCode.RUN_NOT_FOUND: (ErrorCode.RUN_NOT_FOUND, 404),
    ErrorCode.RUN_NOT_RUNNING: (ErrorCode.RUN_NOT_RUNNING, 409),
    ErrorCode.PROJECT_NOT_FOUND: (ErrorCode.PROJECT_NOT_FOUND, 404),
    ErrorCode.PLAN_NOT_FOUND: (ErrorCode.PLAN_NOT_FOUND, 404),
    ErrorCode.ARTIFACT_NOT_FOUND: (ErrorCode.ARTIFACT_NOT_FOUND, 404),
    ErrorCode.STEP_NOT_FOUND: (ErrorCode.STEP_NOT_FOUND, 404),
    ErrorCode.REVIEW_NOT_FOUND: (ErrorCode.REVIEW_NOT_FOUND, 404),
    ErrorCode.INVALID_PROJECT_PATH: (ErrorCode.INVALID_PROJECT_PATH, 400),
    ErrorCode.STORE_ALREADY_EXISTS: (ErrorCode.STORE_ALREADY_EXISTS, 409),
    ErrorCode.STORE_VERSION_INCOMPATIBLE: (ErrorCode.STORE_VERSION_INCOMPATIBLE, 409),
    ErrorCode.RUN_SCOPE_INVALID: (ErrorCode.BAD_REQUEST, 400),
    # 400 — request validation
    ErrorCode.EVIDENCE_VALIDATION_ERROR: (ErrorCode.EVIDENCE_VALIDATION_ERROR, 400),
    # 404 — not found
    # 409 — state conflict / not ready
    ErrorCode.EXPORT_RUN_NOT_FOUND: (ErrorCode.EXPORT_RUN_NOT_FOUND, 409),
    ErrorCode.REPORT_BLOCKED: (ErrorCode.REPORT_BLOCKED, 409),
    ErrorCode.CANONICAL_MANIFEST_MISSING: (ErrorCode.CANONICAL_MANIFEST_MISSING, 404),
    # 500 — infrastructure
    ErrorCode.REGISTRY_CORRUPTED: (ErrorCode.REGISTRY_CORRUPTED, 500),
}


def translate_domain_error(exc: CardreError) -> CardreApiError:
    """Convert a domain ``CardreError`` to the API error envelope.

    The map is the sole source of code translation and HTTP status for mapped
    codes; any explicit domain status is ignored for those. Unmapped codes
    pass through with their domain code and status so no error is ever
    swallowed.
    """
    code, status = _DOMAIN_ERROR_MAP.get(exc.code, (exc.code, exc.status_code))
    return CardreApiError(
        code=code,
        message=str(exc),
        status_code=status,
        context=exc.context,
    )


__all__ = [
    "ErrorCode",
    "CardreApiError",
    "cardre_api_error_handler",
    "cardre_error_handler",
    "error_response",
    "translate_domain_error",
    "unexpected_error_handler",
]
