"""Node-type endpoints — project-scoped node type listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.routes._run_mappings import node_type_to_response
from cardre.api.schemas import NodeTypeListResponse
from cardre.store.db import ProjectStore
from cardre.store.step_repo import StepRepository

router = APIRouter(prefix="/projects/{project_id}", tags=["node_types"])


@router.get("/node-types", response_model=NodeTypeListResponse)
async def list_node_types(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> NodeTypeListResponse:
    """List all available node types for a project."""
    step_repo = StepRepository(store)
    rows = step_repo.get_distinct_node_types(project_id)

    seen: set[str] = set()
    node_types = []
    for r in rows:
        nt = r["node_type"]
        if nt not in seen:
            seen.add(nt)
            node_types.append(node_type_to_response(nt, category=r.get("category", "")))

    return NodeTypeListResponse(node_types=node_types)
