"""Node-type listing endpoint — project-scoped."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.mappers import node_parameter_schema_to_response, node_type_to_response
from cardre.api.schemas import NodeTypeListResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["node-types"])


@router.get("/node-types", response_model=NodeTypeListResponse)
def list_node_types(project_id: str, container=Depends(get_container)):
    catalogue = container.node_catalogue
    node_types = []
    for nt in catalogue.list_types():
        cls = catalogue.resolve(nt)
        schema = cls.parameter_schema()
        schema_response = node_parameter_schema_to_response(schema) if schema is not None else None
        has_params = bool(
            schema is not None
            and any(m.params for m in schema.methods)
        )
        node_types.append(
            node_type_to_response(
                nt,
                category=getattr(cls, "category", ""),
                description=getattr(cls, "description", ""),
                has_params=has_params,
                parameter_schema=schema_response,
            )
        )
    return NodeTypeListResponse(node_types=node_types)
