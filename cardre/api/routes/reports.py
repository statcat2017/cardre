"""Report endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.schemas import ReportListResponse, ReportResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["reports"])


def _project_root(container, project_id: str) -> Path | None:
    return container.project_registry.resolve_root(project_id)


def _collect_manifest_reports(root: Path) -> list[ReportResponse]:
    reports: list[ReportResponse] = []
    exports = root / "exports"
    if not exports.is_dir():
        return reports
    for d in sorted(exports.iterdir()):
        if not d.is_dir() or not d.name.startswith("manifest-"):
            continue
        manifest = d / "manifest.json"
        if manifest.exists():
            run_id = d.name.replace("manifest-", "")
            reports.append(ReportResponse(
                report_id=d.name,
                run_id=run_id,
                report_type="manifest",
                path=str(manifest),
                created_at="",
            ))
    return reports


def _collect_audit_pack_reports(root: Path) -> list[ReportResponse]:
    reports: list[ReportResponse] = []
    exports = root / "exports"
    if not exports.is_dir():
        return reports
    for d in sorted(exports.iterdir()):
        if not d.is_dir() or not d.name.startswith("audit_"):
            continue
        report_dir = d / "report"
        if report_dir.is_dir():
            for html in sorted(report_dir.glob("*.html")):
                reports.append(ReportResponse(
                    report_id=f"{d.name}-report",
                    run_id=None,
                    report_type="audit-pack-report",
                    path=str(html),
                    created_at="",
                ))
    return reports


def _collect_generated_reports(run_id: str | None = None) -> list[ReportResponse]:
    reports: list[ReportResponse] = []
    base = Path.cwd() / "reports"
    if not base.is_dir():
        return reports
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        if run_id is not None and d.name != run_id:
            continue
        html = next(d.glob("*.html"), None)
        if html is not None:
            reports.append(ReportResponse(
                report_id=d.name,
                run_id=d.name,
                report_type="report",
                path=str(html),
                created_at="",
            ))
    return reports


def _run_exists(container, project_id: str, run_id: str) -> bool:
    with container.uow_factory.read_only(project_id) as uow:
        return uow.runs.get(run_id) is not None


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(project_id: str, container=Depends(get_container)):
    root = _project_root(container, project_id)
    reports: list[ReportResponse] = []
    if root is not None:
        reports.extend(_collect_manifest_reports(root))
        reports.extend(_collect_audit_pack_reports(root))
    reports.extend(_collect_generated_reports())
    return ReportListResponse(reports=reports)


@router.get("/runs/{run_id}/reports", response_model=ReportListResponse)
async def list_run_reports(project_id: str, run_id: str, container=Depends(get_container)):
    root = _project_root(container, project_id)
    if root is not None and not _run_exists(container, project_id, run_id):
        raise CardreApiError(
            code=ErrorCode.RUN_NOT_FOUND,
            message=f"Run {run_id!r} not found.",
            status_code=404,
        )
    reports: list[ReportResponse] = []
    if root is not None:
        manifest_dir = root / "exports" / f"manifest-{run_id}"
        if manifest_dir.is_dir():
            manifest = manifest_dir / "manifest.json"
            if manifest.exists():
                reports.append(ReportResponse(
                    report_id=manifest_dir.name,
                    run_id=run_id,
                    report_type="manifest",
                    path=str(manifest),
                    created_at="",
                ))
            html = manifest_dir / "report.html"
            if html.exists():
                reports.append(ReportResponse(
                    report_id=f"{manifest_dir.name}-report",
                    run_id=run_id,
                    report_type="report",
                    path=str(html),
                    created_at="",
                ))
        reports.extend(_collect_audit_pack_reports(root))
    reports.extend(_collect_generated_reports(run_id))
    return ReportListResponse(reports=reports)
