"""Export endpoints — list exports for a project."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.schemas import ExportListResponse, ExportResponse
from cardre.services.export_listing import list_export_dirs
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["exports"])


@router.get("/exports", response_model=ExportListResponse)
async def list_exports(
    project_id: str,
    run_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> ExportListResponse:
    """List exports for a project, optionally filtered by run."""
    dirs = list_export_dirs(store, prefix="export-", run_id=run_id)
    return ExportListResponse(exports=[
        ExportResponse(
            export_id=d.name,
            run_id=d.run_id,
            export_type="scoring_code",
            path=d.path,
            created_at="",
            size_bytes=d.size_bytes,
        )
        for d in dirs
    ])
