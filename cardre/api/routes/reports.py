"""Report endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.schemas import ReportListResponse, ReportResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(project_id: str, container=Depends(get_container)):
    root = container.project_registry.resolve_root(project_id)
    if root is None:
        return ReportListResponse(reports=[])
    exports_dir = root / "exports"
    if not exports_dir.exists():
        return ReportListResponse(reports=[])
    reports = []
    for i, manifest_dir in enumerate(sorted(exports_dir.iterdir()) if exports_dir.is_dir() else []):
        if manifest_dir.is_dir() and manifest_dir.name.startswith("manifest-"):
            manifest_path = manifest_dir / "manifest.json"
            if manifest_path.exists():
                reports.append(ReportResponse(
                    report_id=f"manifest-{i}",
                    run_id=manifest_dir.name.replace("manifest-", ""),
                    report_type="manifest",
                    path=str(manifest_path),
                    created_at="",
                ))
    return ReportListResponse(reports=reports)


@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
async def list_run_reports(project_id: str, run_id: str, container=Depends(get_container)):
    root = container.project_registry.resolve_root(project_id)
    if root is None:
        return ReportListResponse(reports=[])
    manifest_dir = root / "exports" / f"manifest-{run_id}"
    if not manifest_dir.is_dir():
        return ReportListResponse(reports=[])
    reports = []
    manifest_path = manifest_dir / "manifest.json"
    if manifest_path.exists():
        report_path = manifest_dir / "report.html"
        if report_path.exists():
            reports.append(ReportResponse(
                report_id=f"manifest-{run_id}",
                run_id=run_id,
                report_type="report",
                path=str(report_path),
                created_at="",
            ))
        reports.append(ReportResponse(
            report_id=f"manifest-{run_id}",
            run_id=run_id,
            report_type="manifest",
            path=str(manifest_path),
            created_at="",
        ))
    return ReportListResponse(reports=reports)
