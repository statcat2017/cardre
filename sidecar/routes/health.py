from fastapi import APIRouter

from sidecar.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health():
    return HealthResponse()
