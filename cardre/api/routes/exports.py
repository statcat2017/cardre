"""Export endpoints — thin handler calling the ListExports query use case."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.mappers import export_to_response
from cardre.api.schemas import ExportListResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["exports"])


@router.get("/exports", response_model=ExportListResponse)
async def list_exports(project_id: str, run_id: str | None = None, container=Depends(get_container)):
    items = container.list_exports(project_id, run_id=run_id)
    return ExportListResponse(exports=[export_to_response(e) for e in items])
