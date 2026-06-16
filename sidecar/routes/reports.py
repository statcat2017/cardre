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


def _metadata_path(project_root: Path, report_id: str) -> Path:
    return Path(project_root) / "exports" / f"report_{report_id[:8]}" / "report" / "report_metadata.json"


def _save_metadata(project_root: Path, report_id: str, meta: dict) -> None:
    path = _metadata_path(project_root, report_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(meta, indent=2, sort_keys=True))
    except OSError:
        pass


def _load_metadata(project_root: Path, report_id: str) -> dict | None:
    path = _metadata_path(project_root, report_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
    return None

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

    # Store metadata (persisted to disk alongside report files)
    meta = {
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
    _save_metadata(store.root, report_id, meta)

    return GenerateReportResponse(
        report_id=report_id,
        status=readiness.status,
        report_bundle_path=result["bundle_path"],
        html_path=html_path_str,
        export_path=result["export_path"],
        warnings=[ReadinessItem(code=w.code, message=w.message) for w in readiness.warnings],
    )


@router.get("/projects/{project_id}/runs/{run_id}/reports", response_model=list[ReportMetadataResponse])
def list_run_reports(project_id: str, run_id: str):
    """List all generated reports for a given run."""
    store = get_store_for_project(project_id)
    exports_dir = store.root / "exports"
    if not exports_dir.is_dir():
        return []

    reports: list[ReportMetadataResponse] = []
    for report_dir in sorted(exports_dir.iterdir()):
        if not report_dir.is_dir() or not report_dir.name.startswith("report_"):
            continue
        rid = report_dir.name.removeprefix("report_")
        meta = _load_metadata(store.root, rid)
        if meta is None or meta.get("run_id") != run_id:
            continue
        reports.append(ReportMetadataResponse(
            report_id=meta["report_id"],
            created_at=meta.get("created_at", ""),
            target_branch_id=meta.get("target_branch_id", ""),
            report_mode=meta.get("report_mode", ""),
            html_path=meta.get("html_path", ""),
            bundle_path=meta.get("bundle_path", ""),
            export_path=meta.get("export_path", ""),
            status=meta.get("status", ""),
        ))
    return reports


@router.get("/projects/{project_id}/runs/{run_id}/reports/{report_id}", response_model=ReportMetadataResponse)
def get_report_metadata(project_id: str, run_id: str, report_id: str):
    store = get_store_for_project(project_id)
    meta = _load_metadata(store.root, report_id)
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


@router.get("/projects/{project_id}/reports/serve", response_class=HTMLResponse)
def serve_report_file(
    project_id: str,
    path: str = Query(..., description="Relative path to report file within project exports"),
):
    """Serve a report file (HTML or JSON) from a project's exports directory.

    Used by the frontend to open generated reports in a browser tab.
    The path is relative to the project's exports directory
    (e.g. 'report_abc123/report/report.html').
    """
    from cardre.services.project_registry import load_registry
    registry = load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found"})

    project_root = Path(entry["path"])
    exports_root = (project_root / "exports").resolve()
    if path.startswith("exports/"):
        target = (project_root / path).resolve()
    else:
        target = (exports_root / path).resolve()

    if not target.is_relative_to(exports_root):
        raise HTTPException(status_code=403, detail={"code": "PATH_TRAVERSAL", "message": "Path must be within project exports directory"})

    if target.exists() and target.is_file():
        try:
            content = target.read_bytes()
        except OSError:
            raise HTTPException(status_code=500, detail={"code": "FILE_READ_ERROR", "message": f"Could not read file: {path}"})
        if path.endswith(".html"):
            return HTMLResponse(content=content)
        elif path.endswith(".json"):
            from fastapi.responses import JSONResponse
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                raise HTTPException(status_code=500, detail={"code": "INVALID_JSON", "message": f"File is not valid JSON: {path}"})
            return JSONResponse(content=data)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=content)

    raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": f"Report file not found: {path}"})
