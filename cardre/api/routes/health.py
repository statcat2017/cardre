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
    return HealthResponse(
        status="ok",
        version=__version__,
    )
