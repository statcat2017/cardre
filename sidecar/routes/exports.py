"""Export endpoints — selected branch audit pack."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cardre.services.export_service import export_branch_audit_pack
from cardre.services.project_registry import get_store_for_project
from sidecar.models import ExportAuditPackRequest, ExportAuditPackResponse, ExportDiagnostic

router = APIRouter(tags=["exports"])


@router.post("/exports/audit-pack", response_model=ExportAuditPackResponse)
def export_audit_pack(req: ExportAuditPackRequest):
    store = get_store_for_project(req.project_id)
    try:
        result = export_branch_audit_pack(
            store=store,
            project_id=req.project_id,
            plan_id=req.plan_id,
            branch_id=req.branch_id,
            export_path=req.export_path,
            comparison_id=req.comparison_id,
            comparison_snapshot_id=req.comparison_snapshot_id,
            include_row_level_data=req.include_row_level_data,
            include_report=req.include_report,
            report_mode=req.report_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "EXPORT_FAILED", "message": str(exc)})

    return ExportAuditPackResponse(
        export_path=result["export_path"],
        export_id=result["export_id"],
        file_count=result["file_count"],
        warnings=result["warnings"],
        diagnostics=[ExportDiagnostic(**d) for d in result.get("diagnostics", [])],
    )
