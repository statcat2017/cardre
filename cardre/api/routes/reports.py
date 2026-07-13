"""Report endpoints — list and retrieve reports."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.routes._project_scope import run_belongs_to_project
from cardre.api.schemas import ReportListResponse, ReportResponse
from cardre.services.export_listing import list_export_dirs
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ReportListResponse:
    """List all reports for a project."""
    dirs = list_export_dirs(store, prefix="manifest-")
    return ReportListResponse(reports=[
        ReportResponse(
            report_id=d.name,
            run_id=d.run_id,
            report_type="manifest",
            path=str(Path(d.path) / "manifest.json") if (Path(d.path) / "manifest.json").exists() else d.path,
            created_at="",
        )
        for d in dirs
    ])


@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
async def list_run_reports(
    project_id: str,
    run_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ReportListResponse:
    """List reports for a specific run."""
    if not run_belongs_to_project(store, project_id, run_id):
        raise CardreApiError(
            code=ErrorCode.RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    dirs = list_export_dirs(store, prefix="manifest-", run_id=run_id)
    return ReportListResponse(reports=[
        ReportResponse(
            report_id=d.name,
            run_id=d.run_id,
            report_type="manifest",
            path=str(Path(d.path) / "manifest.json") if (Path(d.path) / "manifest.json").exists() else d.path,
            created_at="",
        )
        for d in dirs
    ])
