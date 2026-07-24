"""Report endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.schemas import ReportListResponse, ReportResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(project_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        rows = uow._conn.execute(
            "SELECT * FROM reports WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
    reports = [
        ReportResponse(report_id=r["report_id"], run_id=r.get("run_id"), report_type=r.get("report_type", "governance"),
                       path=r.get("path", ""), created_at=r.get("created_at", ""))
        for r in rows
    ]
    return ReportListResponse(reports=reports)


@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
async def list_run_reports(project_id: str, run_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        rows = uow._conn.execute(
            "SELECT * FROM reports WHERE project_id = ? AND run_id = ? ORDER BY created_at",
            (project_id, run_id),
        ).fetchall()
    reports = [
        ReportResponse(report_id=r["report_id"], run_id=r.get("run_id"), report_type=r.get("report_type", "governance"),
                       path=r.get("path", ""), created_at=r.get("created_at", ""))
        for r in rows
    ]
    return ReportListResponse(reports=reports)
