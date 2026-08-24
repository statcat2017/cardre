"""Report endpoints — thin handlers calling the ListReports query use case."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.mappers import report_to_response
from cardre.api.schemas import ReportListResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


@router.get("/reports", response_model=ReportListResponse)
def list_reports(project_id: str, container=Depends(get_container)):
    items = container.list_reports(project_id)
    return ReportListResponse(reports=[report_to_response(r) for r in items])


@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
def list_run_reports(project_id: str, run_id: str, container=Depends(get_container)):
    items = container.list_reports(project_id, run_id=run_id)
    return ReportListResponse(reports=[report_to_response(r) for r in items])


@router.get("/runs/{run_id}/manifest")
def get_run_manifest(project_id: str, run_id: str, container=Depends(get_container)):
    return container.get_run_manifest(project_id, run_id)
