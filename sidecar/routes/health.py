from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from cardre.registry import NodeRegistry
from cardre.services.project_registry import registry_path, load_registry
from sidecar.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health():
    try:
        load_registry()
        registry_accessible = True
    except Exception:
        registry_accessible = False
    try:
        reg = NodeRegistry.with_defaults()
        node_count = len(reg.list_types())
    except Exception:
        node_count = 0
    return HealthResponse(
        status="ok",
        registry_accessible=registry_accessible,
        registered_node_count=node_count,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
