"""Health-check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre._version import __version__
from cardre.api.dependencies import get_container
from cardre.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(container: object = Depends(get_container)) -> HealthResponse:
    """Return API health status."""
    settings = getattr(container, "settings", None)
    governance_enabled = getattr(settings, "governance_enabled", False) if settings else False
    return HealthResponse(
        status="ok",
        version=__version__,
        governance_enabled=governance_enabled,
    )
