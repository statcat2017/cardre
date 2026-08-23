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
    api_error = translate_domain_error(exc)
    return error_response(
        code=api_error.code,
        message=api_error.message,
        status_code=api_error.status_code,
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
# Maps a domain ``CardreError.code`` to the API ``ErrorCode`` + default HTTP
# status. An explicit status on a domain error remains authoritative because
# some codes describe different contextual states at different seams.
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
    # 400 — request validation
    "SEGMENT_FILTER_RULES_REQUIRED": (ErrorCode.SEGMENT_FILTER_RULES_REQUIRED, 400),
    "SEGMENT_FILTER_REQUIRED": (ErrorCode.SEGMENT_FILTER_REQUIRED, 400),
    "SEGMENT_FILTER_INVALID": (ErrorCode.SEGMENT_FILTER_INVALID, 400),
    "SEGMENT_FILTER_UNSUPPORTED_OPERATOR": (ErrorCode.SEGMENT_FILTER_UNSUPPORTED_OPERATOR, 400),
    "SEGMENT_FILTER_REASON_REQUIRED": (ErrorCode.SEGMENT_FILTER_REASON_REQUIRED, 400),
    "SEGMENT_FILTER_VALUE_REQUIRED": (ErrorCode.SEGMENT_FILTER_VALUE_REQUIRED, 400),
    "BRANCH_NAME_REQUIRED": (ErrorCode.BRANCH_NAME_REQUIRED, 400),
    "BRANCH_REASON_REQUIRED": (ErrorCode.BRANCH_REASON_REQUIRED, 400),
    "BRANCH_TYPE_MISMATCH": (ErrorCode.BRANCH_TYPE_MISMATCH, 400),
    "BRANCH_POINT_NOT_ALLOWED": (ErrorCode.BRANCH_POINT_NOT_ALLOWED, 400),
    "BRANCH_POINT_NOT_IN_PLAN": (ErrorCode.BRANCH_POINT_NOT_IN_PLAN, 400),
    "BRANCH_SCOPE_MISMATCH": (ErrorCode.BRANCH_SCOPE_MISMATCH, 400),
    "BRANCH_NOT_ACTIVE": (ErrorCode.BRANCH_NOT_ACTIVE, 400),
    "BRANCH_PLAN_VERSION_MISMATCH": (ErrorCode.BRANCH_PLAN_VERSION_MISMATCH, 400),
    "CHAMPION_REASON_REQUIRED": (ErrorCode.CHAMPION_REASON_REQUIRED, 400),
    "CHAMPION_BRANCH_MISMATCH": (ErrorCode.CHAMPION_BRANCH_MISMATCH, 400),
    "BRANCH_NOT_IN_COMPARISON": (ErrorCode.BRANCH_NOT_IN_COMPARISON, 400),
    "EVIDENCE_VALIDATION_ERROR": (ErrorCode.EVIDENCE_VALIDATION_ERROR, 400),
    "REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF": (ErrorCode.REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF, 400),
    "REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD": (ErrorCode.REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD, 400),
    # 404 — not found
    "COMPARISON_SNAPSHOT_NOT_FOUND": (ErrorCode.COMPARISON_SNAPSHOT_NOT_FOUND, 404),
    "EXPORT_RUN_NOT_FOUND": (ErrorCode.EXPORT_RUN_NOT_FOUND, 404),
    # 409 — state conflict / not ready
    "STALE_HEAD_VERSION": (ErrorCode.STALE_HEAD_VERSION, 409),
    "STALE_BASE_VERSION": (ErrorCode.STALE_BASE_VERSION, 409),
    "STALE_SNAPSHOT": (ErrorCode.STALE_SNAPSHOT, 409),
    "COMPARISON_NOT_READY": (ErrorCode.COMPARISON_NOT_READY, 409),
    "REPORT_BLOCKED": (ErrorCode.REPORT_BLOCKED, 409),
    "CANONICAL_MANIFEST_MISSING": (ErrorCode.CANONICAL_MANIFEST_MISSING, 404),
    # 500 — infrastructure
    "REGISTRY_CORRUPTED": (ErrorCode.REGISTRY_CORRUPTED, 500),
}


def translate_domain_error(exc: CardreError) -> CardreApiError:
    """Convert a domain ``CardreError`` to the API error envelope.

    Uses the central code/status map for code translation and default status;
    an explicit domain status remains authoritative. Unknown codes pass
    through with their domain code and status so no error is ever swallowed.
    """
    code, status = _DOMAIN_ERROR_MAP.get(exc.code, (exc.code, exc.status_code))
    if getattr(exc, "_status_code_explicit", False):
        status = exc.status_code
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
