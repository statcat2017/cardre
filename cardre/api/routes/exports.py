"""Export endpoints — thin handler calling the ListExports query use case."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from cardre.api.dependencies import get_container
from cardre.api.mappers import export_to_response
from cardre.api.schemas import ErrorResponse, ExportListResponse, ExportResponse
from cardre.application.reporting.export_audit_pack import ExportAuditPackCommand
from cardre.domain.errors import CardreError, ErrorCode

router = APIRouter(prefix="/projects/{project_id}", tags=["exports"])


@router.get("/exports", response_model=ExportListResponse)
def list_exports(project_id: str, run_id: str | None = None, container=Depends(get_container)):
    items = container.list_exports(project_id, run_id=run_id)
    return ExportListResponse(exports=[_export_response(project_id, e) for e in items])


@router.post(
    "/runs/{run_id}/exports/audit-pack",
    status_code=201,
    response_model=ExportResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def generate_audit_pack(project_id: str, run_id: str, container=Depends(get_container)):
    result = container.export_audit_pack(
        ExportAuditPackCommand(project_id=project_id, run_id=run_id),
    )
    item = next(
        (
            export for export in container.list_exports(project_id, run_id=run_id)
            if export.export_id == result.export_id
        ),
        None,
    )
    if item is None:
        raise CardreError(
            "Generated audit pack was not registered for this run.",
            code=ErrorCode.ARTIFACT_NOT_FOUND,
            context={"run_id": run_id, "export_id": result.export_id},
        )
    return _export_response(project_id, item)


@router.get(
    "/runs/{run_id}/exports/{export_id}/download",
    response_class=FileResponse,
    responses={
        200: {
            "description": "Downloadable checksummed audit pack archive.",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {"model": ErrorResponse},
    },
)
def download_audit_pack(
    project_id: str, run_id: str, export_id: str, container=Depends(get_container)
):
    item = container.download_audit_pack(project_id, run_id, export_id)
    return FileResponse(
        path=item.file_path,
        media_type=item.media_type,
        filename=item.file_name,
        headers={
            "X-Content-Type-Options": "nosniff",
        },
        background=(
            BackgroundTask(item.file_path.unlink, missing_ok=True)
            if item.delete_after_download
            else None
        ),
    )


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


def _export_response(project_id: str, item) -> ExportResponse:
    response = export_to_response(item)
    if item.export_type == "audit_pack":
        response.download_url = (
            f"/projects/{project_id}/runs/{item.run_id}/exports/"
            f"{item.export_id}/download"
        )
    return response
