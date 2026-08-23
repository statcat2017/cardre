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
    ErrorCode.BRANCH_NOT_FOUND: (ErrorCode.BRANCH_NOT_FOUND, 404),
    ErrorCode.COMPARISON_NOT_FOUND: (ErrorCode.COMPARISON_NOT_FOUND, 404),
    ErrorCode.REVIEW_NOT_FOUND: (ErrorCode.REVIEW_NOT_FOUND, 404),
    ErrorCode.INVALID_PROJECT_PATH: (ErrorCode.INVALID_PROJECT_PATH, 400),
    ErrorCode.STORE_ALREADY_EXISTS: (ErrorCode.STORE_ALREADY_EXISTS, 409),
    ErrorCode.STORE_VERSION_INCOMPATIBLE: (ErrorCode.STORE_ALREADY_EXISTS, 409),
    ErrorCode.BRANCH_VALIDATION_ERROR: (ErrorCode.BAD_REQUEST, 400),
    ErrorCode.RUN_SCOPE_INVALID: (ErrorCode.BAD_REQUEST, 400),
    # 400 — request validation
    ErrorCode.SEGMENT_FILTER_RULES_REQUIRED: (ErrorCode.SEGMENT_FILTER_RULES_REQUIRED, 400),
    ErrorCode.SEGMENT_FILTER_REQUIRED: (ErrorCode.SEGMENT_FILTER_REQUIRED, 400),
    ErrorCode.SEGMENT_FILTER_INVALID: (ErrorCode.SEGMENT_FILTER_INVALID, 400),
    ErrorCode.SEGMENT_FILTER_UNSUPPORTED_OPERATOR: (ErrorCode.SEGMENT_FILTER_UNSUPPORTED_OPERATOR, 400),
    ErrorCode.SEGMENT_FILTER_REASON_REQUIRED: (ErrorCode.SEGMENT_FILTER_REASON_REQUIRED, 400),
    ErrorCode.SEGMENT_FILTER_VALUE_REQUIRED: (ErrorCode.SEGMENT_FILTER_VALUE_REQUIRED, 400),
    ErrorCode.BRANCH_NAME_REQUIRED: (ErrorCode.BRANCH_NAME_REQUIRED, 400),
    ErrorCode.BRANCH_REASON_REQUIRED: (ErrorCode.BRANCH_REASON_REQUIRED, 400),
    ErrorCode.BRANCH_TYPE_MISMATCH: (ErrorCode.BRANCH_TYPE_MISMATCH, 400),
    ErrorCode.BRANCH_POINT_NOT_ALLOWED: (ErrorCode.BRANCH_POINT_NOT_ALLOWED, 400),
    ErrorCode.BRANCH_POINT_NOT_IN_PLAN: (ErrorCode.BRANCH_POINT_NOT_IN_PLAN, 400),
    ErrorCode.BRANCH_SCOPE_MISMATCH: (ErrorCode.BRANCH_SCOPE_MISMATCH, 400),
    ErrorCode.BRANCH_NOT_ACTIVE: (ErrorCode.BRANCH_NOT_ACTIVE, 400),
    ErrorCode.BRANCH_PLAN_VERSION_MISMATCH: (ErrorCode.BRANCH_PLAN_VERSION_MISMATCH, 400),
    ErrorCode.CHAMPION_REASON_REQUIRED: (ErrorCode.CHAMPION_REASON_REQUIRED, 400),
    ErrorCode.CHAMPION_BRANCH_MISMATCH: (ErrorCode.CHAMPION_BRANCH_MISMATCH, 400),
    ErrorCode.BRANCH_NOT_IN_COMPARISON: (ErrorCode.BRANCH_NOT_IN_COMPARISON, 400),
    ErrorCode.EVIDENCE_VALIDATION_ERROR: (ErrorCode.EVIDENCE_VALIDATION_ERROR, 400),
    ErrorCode.REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF: (ErrorCode.REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF, 400),
    ErrorCode.REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD: (ErrorCode.REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD, 400),
    # 404 — not found
    ErrorCode.COMPARISON_SNAPSHOT_NOT_FOUND: (ErrorCode.COMPARISON_SNAPSHOT_NOT_FOUND, 404),
    ErrorCode.EXPORT_RUN_NOT_FOUND: (ErrorCode.EXPORT_RUN_NOT_FOUND, 404),
    # 409 — state conflict / not ready
    ErrorCode.STALE_HEAD_VERSION: (ErrorCode.STALE_HEAD_VERSION, 409),
    ErrorCode.STALE_BASE_VERSION: (ErrorCode.STALE_BASE_VERSION, 409),
    ErrorCode.STALE_SNAPSHOT: (ErrorCode.STALE_SNAPSHOT, 409),
    ErrorCode.COMPARISON_NOT_READY: (ErrorCode.COMPARISON_NOT_READY, 409),
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
    "GovernanceNotEnabled",
    "cardre_api_error_handler",
    "cardre_error_handler",
    "error_response",
    "translate_domain_error",
]
