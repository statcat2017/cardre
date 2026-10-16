"""Export endpoints — thin handler calling the ListExports query use case."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from cardre.api.dependencies import get_container
from cardre.api.mappers import export_to_response
from cardre.api.schemas import ErrorResponse, ExportListResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["exports"])


@router.get("/exports", response_model=ExportListResponse)
def list_exports(project_id: str, run_id: str | None = None, container=Depends(get_container)):
    items = container.list_exports(project_id, run_id=run_id)
    return ExportListResponse(exports=[export_to_response(e) for e in items])


@router.get(
    "/runs/{run_id}/exports/download",
    response_class=Response,
    responses={
        200: {
            "description": "Rendered presentation of an immutable scoring output artifact.",
            "content": {
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
                "text/x-python": {"schema": {"type": "string", "format": "binary"}},
                "application/sql": {"schema": {"type": "string", "format": "binary"}},
            },
        },
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def download_scoring_export(
    project_id: str,
    run_id: str,
    artifact_id: str,
    container=Depends(get_container),
):
    item = container.download_scoring_export(project_id, run_id, artifact_id)
    return Response(
        content=item.content,
        media_type=item.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{item.file_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
