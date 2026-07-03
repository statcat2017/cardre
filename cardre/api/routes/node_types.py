"""Node-type endpoints — project-scoped node type listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.schemas import NodeTypeListResponse, NodeTypeResponse
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
    node_types: list[NodeTypeResponse] = []
    for r in rows:
        nt = r["node_type"]
        if nt not in seen:
            seen.add(nt)
            node_types.append(NodeTypeResponse(
                node_type=nt,
                display_name=nt.split(".")[-1] if "." in nt else nt,
                description="",
                category=r.get("category", ""),
                tier="launch",
                has_params=True,
            ))

    if not node_types:
        # Return some well-known defaults if no data yet
        defaults = [
            ("cardre.import_data", "import", True),
            ("cardre.profile", "fit", True),
            ("cardre.fine_classing", "fit", True),
            ("cardre.manual_binning", "refinement", True),
            ("cardre.woe_transform", "transform", True),
            ("cardre.logistic_regression", "fit", True),
            ("cardre.score_scaling", "transform", True),
        ]
        for nt, cat, _ in defaults:
            node_types.append(NodeTypeResponse(
                node_type=nt,
                display_name=nt.split(".")[-1],
                description="",
                category=cat,
                tier="launch",
                has_params=True,
            ))

    return NodeTypeListResponse(node_types=node_types)
