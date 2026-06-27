from datetime import datetime, timezone

from fastapi import APIRouter

from cardre.registry import NodeRegistry
from cardre.services.project_registry import load_registry
from sidecar.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health():
    diagnostics: list[dict] = []
    try:
        load_registry()
        registry_accessible = True
    except Exception as exc:
        registry_accessible = False
        diagnostics.append({"code": "REGISTRY_UNREACHABLE", "message": str(exc)})
    try:
        reg = NodeRegistry.with_defaults()
        node_count = len(reg.list_types())
        launch_count = len(reg.list_launch_nodes())
        deferred_count = len(reg.list_deferred_nodes())
    except Exception as exc:
        node_count = 0
        launch_count = 0
        deferred_count = 0
        diagnostics.append({"code": "NODE_REGISTRY_FAILED", "message": str(exc)})
    try:
        from cardre.store.project_store import _governance_enabled
        governance_enabled = _governance_enabled()
    except Exception as exc:
        governance_enabled = False
        diagnostics.append({"code": "GOVERNANCE_CHECK_FAILED", "message": str(exc)})
    status = "ok" if not diagnostics else "degraded"
    return HealthResponse(
        status=status,
        registry_accessible=registry_accessible,
        registered_node_count=node_count,
        launch_node_count=launch_count,
        deferred_node_count=deferred_count,
        governance_enabled=governance_enabled,
        checked_at=datetime.now(timezone.utc).isoformat(),
        diagnostics=diagnostics,
    )
