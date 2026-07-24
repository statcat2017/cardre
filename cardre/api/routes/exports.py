"""Export endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.schemas import ExportListResponse, ExportResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["exports"])


@router.get("/exports", response_model=ExportListResponse)
async def list_exports(project_id: str, run_id: str | None = None, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        rows = uow._conn.execute(
            "SELECT * FROM exports WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
    exports = [
        ExportResponse(
            export_id=r["export_id"], run_id=r["run_id"],
            export_type=r.get("export_type", "audit"), path=r.get("path", ""),
            created_at=r.get("created_at", ""), size_bytes=r.get("size_bytes", 0),
        )
        for r in rows
        if run_id is None or r["run_id"] == run_id
    ]
    return ExportListResponse(exports=exports)
