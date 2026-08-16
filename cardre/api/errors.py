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

from cardre.domain.errors import CardreError, ErrorCode

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


class GovernanceNotEnabled(CardreApiError):
    """Raised when governance is disabled and a governance endpoint is called."""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.GOVERNANCE_DISABLED,
            message="Governance is not enabled. Set CARDRE_GOVERNANCE=1 to enable.",
            status_code=403,
        )


# ---------------------------------------------------------------------------
# Domain error translation
# ---------------------------------------------------------------------------
# Maps a domain ``CardreError.code`` to the API ``ErrorCode`` + HTTP status.
# Codes not listed pass through with their domain code/status unchanged.
# This is the single home for the per-route try/except ladders that used to
# live in every route file.

_DOMAIN_ERROR_MAP: dict[str, tuple[str, int]] = {
    "PLAN_VERSION_NOT_FOUND": (ErrorCode.PLAN_VERSION_NOT_FOUND, 404),
    "PLAN_VERSION_ALREADY_COMMITTED": (ErrorCode.PLAN_VERSION_IMMUTABLE, 409),
    "PLAN_VERSION_NOT_COMMITTED": (ErrorCode.PLAN_VERSION_IMMUTABLE, 409),
    "CONCURRENT_RUN": (ErrorCode.CONCURRENT_RUN, 409),
    "RUN_NOT_FOUND": (ErrorCode.RUN_NOT_FOUND, 404),
    "RUN_NOT_RUNNING": (ErrorCode.RUN_NOT_RUNNING, 409),
    "PROJECT_NOT_FOUND": (ErrorCode.PROJECT_NOT_FOUND, 404),
    "PLAN_NOT_FOUND": (ErrorCode.PLAN_NOT_FOUND, 404),
    "ARTIFACT_NOT_FOUND": (ErrorCode.ARTIFACT_NOT_FOUND, 404),
    "STEP_NOT_FOUND": (ErrorCode.STEP_NOT_FOUND, 404),
    "BRANCH_NOT_FOUND": (ErrorCode.BRANCH_NOT_FOUND, 404),
    "COMPARISON_NOT_FOUND": (ErrorCode.COMPARISON_NOT_FOUND, 404),
    "REVIEW_NOT_FOUND": (ErrorCode.REVIEW_NOT_FOUND, 404),
    "INVALID_PROJECT_PATH": (ErrorCode.INVALID_PROJECT_PATH, 400),
    "STORE_ALREADY_EXISTS": (ErrorCode.STORE_ALREADY_EXISTS, 409),
    "STORE_VERSION_INCOMPATIBLE": (ErrorCode.STORE_ALREADY_EXISTS, 409),
    "BRANCH_VALIDATION_ERROR": (ErrorCode.BAD_REQUEST, 400),
    "RUN_SCOPE_INVALID": (ErrorCode.BAD_REQUEST, 400),
}


def translate_domain_error(exc: CardreError) -> CardreApiError:
    """Convert a domain ``CardreError`` to the API error envelope.

    Uses the central code/status map; unknown codes pass through with their
    domain code and status so no error is ever swallowed.
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
    "GovernanceNotEnabled",
    "cardre_api_error_handler",
    "cardre_error_handler",
    "error_response",
    "translate_domain_error",
]
