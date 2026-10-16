"""Project- and run-scoped report endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Response

from cardre.api.dependencies import get_container
from cardre.api.mappers import report_to_response
from cardre.api.schemas import ErrorResponse, ReportListResponse, ReportResponse
from cardre.application.reporting.generate_report import GenerateReportCommand
from cardre.domain.errors import CardreError, ErrorCode

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])
_REPORT_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; object-src 'none'",
}


@router.get("/reports", response_model=ReportListResponse)
def list_reports(project_id: str, container=Depends(get_container)):
    items = container.list_reports(project_id)
    return ReportListResponse(reports=[_report_response(project_id, r) for r in items])


@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
def list_run_reports(project_id: str, run_id: str, container=Depends(get_container)):
    items = container.list_reports(project_id, run_id=run_id)
    return ReportListResponse(reports=[_report_response(project_id, r) for r in items])


@router.post(
    "/runs/{run_id}/reports",
    status_code=201,
    response_model=ReportResponse,
    responses={409: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def generate_run_report(project_id: str, run_id: str, container=Depends(get_container)):
    result = container.generate_report(GenerateReportCommand(project_id=project_id, run_id=run_id))
    if result.report_id is None:
        raise CardreError(
            "Generated report was not stored inside the project.",
            code=ErrorCode.ARTIFACT_NOT_FOUND,
            context={"run_id": run_id},
        )
    report = next(
        (
            item
            for item in container.list_reports(project_id, run_id=run_id)
            if item.report_id == result.report_id
        ),
        None,
    )
    if report is None:
        raise CardreError(
            "Generated report was not registered for this run.",
            code=ErrorCode.ARTIFACT_NOT_FOUND,
            context={"run_id": run_id, "report_id": result.report_id},
        )
    return _report_response(project_id, report)


@router.get(
    "/runs/{run_id}/reports/{report_id}/html",
    response_class=Response,
    responses={
        200: {
            "description": "Inline HTML model development report.",
            "content": {"text/html": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {"model": ErrorResponse},
    },
)
def open_run_report(project_id: str, run_id: str, report_id: str, container=Depends(get_container)):
    item = container.read_report_html(project_id, run_id, report_id)
    return Response(
        content=item.content,
        media_type="text/html",
        headers={
            **_REPORT_SECURITY_HEADERS,
            "Content-Disposition": 'inline; filename="model-development-report.html"',
        },
    )


@router.get(
    "/runs/{run_id}/reports/{report_id}/download",
    response_class=Response,
    responses={
        200: {
            "description": "Downloadable HTML model development report.",
            "content": {"text/html": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {"model": ErrorResponse},
    },
)
def download_run_report(
    project_id: str, run_id: str, report_id: str, container=Depends(get_container)
):
    item = container.read_report_html(project_id, run_id, report_id)
    return Response(
        content=item.content,
        media_type="text/html",
        headers={
            **_REPORT_SECURITY_HEADERS,
            "Content-Disposition": 'attachment; filename="model-development-report.html"',
        },
    )


@router.get("/runs/{run_id}/manifest")
def get_run_manifest(project_id: str, run_id: str, container=Depends(get_container)):
    return container.get_run_manifest(project_id, run_id)


def _report_response(project_id: str, item) -> ReportResponse:
    response = report_to_response(item)
    stored_path = Path(item.path)
    if (
        item.report_type == "report"
        and item.run_id
        and not stored_path.is_absolute()
        and ".." not in stored_path.parts
    ):
        base = f"/projects/{project_id}/runs/{item.run_id}/reports/{item.report_id}"
        response.file_name = "model-development-report.html"
        response.open_url = f"{base}/html"
        response.download_url = f"{base}/download"
    return response
