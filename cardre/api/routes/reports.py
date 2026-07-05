"""Report endpoints — list and retrieve reports."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.errors import RUN_NOT_FOUND, CardreApiError
from cardre.api.routes._project_scope import run_belongs_to_project
from cardre.api.schemas import ReportListResponse, ReportResponse
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ReportListResponse:
    """List all reports for a project."""
    reports: list[ReportResponse] = []
    exports_dir = store.root / "exports"
    if exports_dir.exists():
        for item in sorted(exports_dir.iterdir()):
            if item.is_dir() and item.name.startswith("manifest-"):
                parts = item.name.split("-", 1)
                run_id = parts[1] if len(parts) > 1 else ""
                reports.append(ReportResponse(
                    report_id=item.name,
                    run_id=run_id,
                    report_type="manifest",
                    path=str(item / "manifest.json") if (item / "manifest.json").exists() else str(item),
                    created_at="",
                ))
    return ReportListResponse(reports=reports)


@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
async def list_run_reports(
    project_id: str,
    run_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ReportListResponse:
    """List reports for a specific run."""
    if not run_belongs_to_project(store, project_id, run_id):
        raise CardreApiError(
            code=RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    reports: list[ReportResponse] = []
    exports_dir = store.root / "exports"
    manifest_dir = exports_dir / f"manifest-{run_id}"
    if manifest_dir.exists():
        reports.append(ReportResponse(
            report_id=f"manifest-{run_id}",
            run_id=run_id,
            report_type="manifest",
            path=str(manifest_dir / "manifest.json") if (manifest_dir / "manifest.json").exists() else str(manifest_dir),
            created_at="",
        ))
    return ReportListResponse(reports=reports)
