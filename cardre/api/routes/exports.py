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
            "SELECT * FROM exports ORDER BY created_at",
        ).fetchall()
    exports = []
    for r in rows:
        rid = r["run_id"]
        if run_id is not None and rid != run_id:
            continue
        exports.append(ExportResponse(
            export_id=r["export_id"],
            run_id=rid,
            export_type=r["export_type"],
            path=r["path"],
            created_at=r["created_at"],
            size_bytes=r["size_bytes"],
        ))
    return ExportListResponse(exports=exports)
