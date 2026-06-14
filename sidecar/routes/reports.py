"""Phase 5 report endpoints — readiness, generation, and metadata."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from cardre.services.project_registry import get_store_for_project, ProjectNotFoundError
from cardre.services.report_generation_service import ReportGenerationError, ReportGenerationService

from cardre.store import ProjectStore
from sidecar.models import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReadinessItem,
    ReportMetadataResponse,
    ReportReadinessRequest,
    ReportReadinessResponse,
)
router = APIRouter(tags=["reports"])

# In-memory report metadata registry (reports are persisted on disk as files)
_report_registry: dict[str, dict] = {}


@router.post("/projects/{project_id}/runs/{run_id}/report-readiness", response_model=ReportReadinessResponse)
def get_report_readiness(project_id: str, run_id: str, req: ReportReadinessRequest):
    store = get_store_for_project(project_id)
    try:
        svc = ReportGenerationService(store)
        result = svc.check_readiness(
            project_id=project_id,
            run_id=run_id,
            target_branch_id=req.target_branch_id,
            report_mode=req.report_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "READINESS_FAILED", "message": str(exc)})

    return ReportReadinessResponse(
        ready=result.ready,
        status=result.status,
        blockers=[ReadinessItem(code=b.code, message=b.message) for b in result.blockers],
        warnings=[ReadinessItem(code=w.code, message=w.message) for w in result.warnings],
    )


@router.post("/projects/{project_id}/runs/{run_id}/reports", response_model=GenerateReportResponse, status_code=201)
def generate_report(project_id: str, run_id: str, req: GenerateReportRequest):
    store = get_store_for_project(project_id)
    svc = ReportGenerationService(store)

    # Use the service for the full pipeline
    report_id = str(uuid.uuid4())
    output_dir = store.root / "exports" / f"report_{report_id[:8]}"

    try:
        result = svc.generate_report(
            project_id=project_id,
            run_id=run_id,
            target_branch_id=req.target_branch_id,
            report_mode=req.report_mode,
            output_dir=output_dir,
        )
    except ReportGenerationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "REPORT_BLOCKED", "message": f"Report generation blocked: {exc.blockers}"},
        )

    readiness = result["readiness"]
    bundle = result["bundle"]

    # Override html_path to empty if not requested
    html_path_str = result["html_path"]
    if "html" not in req.output_formats:
        html_path_str = ""

    # Store metadata
    _report_registry[report_id] = {
        "report_id": report_id,
        "project_id": project_id,
        "run_id": run_id,
        "created_at": bundle.generated_at,
        "target_branch_id": req.target_branch_id,
        "report_mode": req.report_mode,
        "html_path": html_path_str,
        "bundle_path": result["bundle_path"],
        "export_path": result["export_path"],
        "status": readiness.status,
    }

    return GenerateReportResponse(
        report_id=report_id,
        status=readiness.status,
        report_bundle_path=result["bundle_path"],
        html_path=html_path_str,
        export_path=result["export_path"],
        warnings=[ReadinessItem(code=w.code, message=w.message) for w in readiness.warnings],
    )


@router.get("/projects/{project_id}/runs/{run_id}/reports/{report_id}", response_model=ReportMetadataResponse)
def get_report_metadata(project_id: str, run_id: str, report_id: str):
    meta = _report_registry.get(report_id)
    if meta is None:
        raise HTTPException(status_code=404, detail={"code": "REPORT_NOT_FOUND", "message": f"No report with ID {report_id}"})

    return ReportMetadataResponse(
        report_id=meta["report_id"],
        created_at=meta.get("created_at", ""),
        target_branch_id=meta.get("target_branch_id", ""),
        report_mode=meta.get("report_mode", ""),
        html_path=meta.get("html_path", ""),
        bundle_path=meta.get("bundle_path", ""),
        export_path=meta.get("export_path", ""),
        status=meta.get("status", ""),
    )


@router.get("/reports/serve", response_class=HTMLResponse)
def serve_report_file(path: str = Query(..., description="Relative path to report file within project root")):
    """Serve a report file (HTML or JSON) from any project's exports directory.

    Used by the frontend to open generated reports in a browser tab.
    The path is relative to the project root (e.g. 'exports/report_abc123/report/report.html').
    """
    from cardre.services.project_registry import load_registry
    registry = load_registry()
    for _pid, entry in registry.items():
        project_root = Path(entry["path"])
        target = project_root / path
        if target.exists() and target.is_file():
            content = target.read_bytes()
            if path.endswith(".html"):
                return HTMLResponse(content=content)
            elif path.endswith(".json"):
                from fastapi.responses import JSONResponse
                data = json.loads(content)
                return JSONResponse(content=data)
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(content=content)
    raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": f"Report file not found: {path}"})
