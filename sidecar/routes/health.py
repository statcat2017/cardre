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
        launch_count = len(reg.list_launch_nodes())
        deferred_count = len(reg.list_deferred_nodes())
    except Exception:
        node_count = 0
        launch_count = 0
        deferred_count = 0
    try:
        from cardre.store.project_store import _governance_enabled
        governance_enabled = _governance_enabled()
    except Exception:
        governance_enabled = False
    return HealthResponse(
        status="ok",
        registry_accessible=registry_accessible,
        registered_node_count=node_count,
        launch_node_count=launch_count,
        deferred_node_count=deferred_count,
        governance_enabled=governance_enabled,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
