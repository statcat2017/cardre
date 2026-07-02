"""Export endpoints — list exports for a project."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.schemas import ExportListResponse, ExportResponse
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["exports"])


@router.get("/exports", response_model=ExportListResponse)
async def list_exports(
    project_id: str,
    run_id: str | None = None,
    store: ProjectStore = Depends(get_project_store),
) -> ExportListResponse:
    """List exports for a project, optionally filtered by run."""
    exports: list[ExportResponse] = []
    # Exports are stored as directories under store.root / exports/
    exports_dir = store.root / "exports"
    if exports_dir.exists():
        for item in sorted(exports_dir.iterdir()):
            if item.is_dir() and item.name.startswith("export-"):
                parts = item.name.split("-", 2)
                export_id = item.name
                export_run_id = parts[1] if len(parts) > 1 else ""
                if run_id and export_run_id != run_id:
                    continue
                size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                exports.append(ExportResponse(
                    export_id=export_id,
                    run_id=export_run_id,
                    export_type="scoring_code",
                    path=str(item),
                    created_at="",
                    size_bytes=size,
                ))
    return ExportListResponse(exports=exports)
