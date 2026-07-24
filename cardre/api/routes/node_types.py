"""Node-type listing endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.mappers import node_type_to_response
from cardre.api.schemas import NodeTypeListResponse

router = APIRouter(tags=["node-types"])


@router.get("/node-types", response_model=NodeTypeListResponse)
async def list_node_types(container=Depends(get_container)):
    catalogue = container.node_catalogue
    node_types = [
        node_type_to_response(
            nt,
            category=getattr(catalogue.resolve(nt), "category", ""),
            tier=getattr(catalogue.availability(nt), "tier", "launch"),
            has_params=True,
        )
        for nt in catalogue.list_types()
    ]
    return NodeTypeListResponse(node_types=node_types)
