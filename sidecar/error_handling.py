"""Standard API error envelope and request-id middleware for the Cardre sidecar.

Every exception is normalised into one shape:

  {"detail": {"code": ..., "message": ..., "recoverable": ..., "severity": ...,
              "context": ..., "diagnostics": [...], "request_id": ..., "error_id": ...}}
"""

from __future__ import annotations

import logging
import uuid
import traceback as tb_module
from typing import Any

from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from cardre.errors import CardreError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request-context middleware
# ---------------------------------------------------------------------------


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Generates X-Cardre-Request-Id, stores it on request.state, and logs
    every request with method, path, status, elapsed time, and request id."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        import time
        start = time.perf_counter()
        request_id = request.headers.get("X-Cardre-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Cardre-Request-Id"] = request_id
        logger.info(
            "%s %s %s (%.3fs) [%s]",
            request.method, request.url.path, response.status_code, elapsed, request_id,
        )
        return response


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def _envelope(
    code: str,
    message: str,
    status_code: int,
    *,
    recoverable: bool = False,
    severity: str = "error",
    context: dict[str, Any] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
    error_id: str | None = None,
) -> JSONResponse:
    error_id = error_id or str(uuid.uuid4())
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "code": code,
                "message": message,
                "recoverable": recoverable,
                "severity": severity,
                "context": context or {},
                "diagnostics": diagnostics or [],
                "request_id": request_id or "",
                "error_id": error_id,
            }
        },
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


def cardre_error_handler(request: Request, exc: CardreError) -> JSONResponse:
    """Serialise any CardreError subclass via its to_envelope() method."""
    env = exc.to_envelope()
    env["request_id"] = _request_id(request)
    env["error_id"] = str(uuid.uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": env},
    )


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalise HTTPException into the standard envelope.

    Handles both dict-shaped detail (code + message) and string-shaped
    detail (legacy routes that haven't been swept yet).
    """
    rid = _request_id(request)
    eid = str(uuid.uuid4())
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        env = dict(detail)
        env.setdefault("recoverable", False)
        env.setdefault("severity", "error")
        env.setdefault("context", {})
        env.setdefault("diagnostics", [])
    else:
        env = {
            "code": "HTTP_ERROR",
            "message": str(detail) if detail else f"HTTP {exc.status_code}",
            "recoverable": False,
            "severity": "error",
            "context": {},
            "diagnostics": [],
        }
    env["request_id"] = rid
    env["error_id"] = eid
    return JSONResponse(status_code=exc.status_code, content={"detail": env})


def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Map FastAPI's RequestValidationError into the standard envelope.

    Pydantic errors are placed inside detail.diagnostics, not at the
    top level, so frontend fetchJson's ApiError parsing still works.
    """
    diags = []
    for err in exc.errors():
        diags.append({
            "code": "VALIDATION_ERROR",
            "message": err.get("msg", ""),
            "source": "pydantic",
            "context": {"loc": list(err.get("loc", [])), "type": err.get("type", "")},
        })
    return _envelope(
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        status_code=422,
        diagnostics=diags,
        request_id=_request_id(request),
    )


def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map any unhandled exception to INTERNAL_ERROR.

    The full traceback is logged server-side with the request id.
    The response body contains only the exception type and a short
    message in diagnostics, never the raw traceback.
    """
    rid = _request_id(request)
    tb_text = "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
    logger.error("Unhandled exception [%s]: %s\n%s", rid, exc, tb_text)
    return _envelope(
        code="INTERNAL_ERROR",
        message="An internal error occurred.",
        status_code=500,
        diagnostics=[{
            "code": "INTERNAL_ERROR",
            "message": f"Unhandled {type(exc).__name__}: {exc}",
            "exception_type": type(exc).__name__,
            "method": request.method,
            "path": str(request.url.path),
        }],
        request_id=rid,
    )
