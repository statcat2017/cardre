"""Health-check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from cardre.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return API health status."""
    return HealthResponse(status="ok", version="0.2.0")
