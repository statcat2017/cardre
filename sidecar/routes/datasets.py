"""Dataset import endpoint — routes through the executor for audit trail.

Thin endpoint: business logic lives in cardre/services/.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.audit import StepSpec, json_logical_hash
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore
from cardre.services.project_registry import get_store_for_project
from cardre.services.import_service import update_plan_import_params, get_or_create_import_plan
from sidecar.models import ArtifactResponse, ImportDatasetRequest

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/import", response_model=ArtifactResponse, status_code=201)
def import_dataset(body: ImportDatasetRequest):
    source = Path(body.source_path).resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail={"code": "FILE_NOT_FOUND", "message": f"Source file not found: {source}"})
    store = get_store_for_project(body.project_id)
    proj = store.get_project(body.project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found in SQLite"})

    # Use a dedicated hidden import plan
    import_plan_id = get_or_create_import_plan(store, body.project_id)

    params = {"source_path": str(source.resolve())}
    if body.format and body.format != "auto":
        params["format"] = body.format
    if body.delimiter is not None:
        params["delimiter"] = body.delimiter
    if not body.has_header:
        params["has_header"] = False
    if body.schema_overrides:
        params["schema_overrides"] = dict(body.schema_overrides)
    if body.max_rows is not None:
        params["max_rows"] = body.max_rows
    if body.encoding is not None:
        params["encoding"] = body.encoding
    if body.null_values:
        params["null_values"] = list(body.null_values)
    import_step = StepSpec(
        step_id="import",
        node_type="cardre.import_dataset",
        node_version="1",
        category="transform",
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=[],
        branch_label="",
        position=0,
    )

    import_pv_id = store.create_plan_version(
        import_plan_id, [import_step],
        description=f"Import {source.name}",
    )

    executor = PlanExecutor(NodeRegistry.with_defaults())
    run_id = executor.run_plan_version(store, import_pv_id)
    run = store.get_run(run_id)

    if run["status"] == "failed":
        raise HTTPException(
            status_code=500,
            detail={"code": "IMPORT_FAILED", "message": f"Dataset import failed: {source.name}"},
        )

    run_steps = store.get_run_steps(run_id)
    if not run_steps:
        raise HTTPException(status_code=500, detail={"code": "NO_RUN_STEPS", "message": "No run steps recorded for import"})

    import_rs = run_steps[0]
    if not import_rs.output_artifact_ids:
        raise HTTPException(status_code=500, detail={"code": "NO_ARTIFACT", "message": "Import produced no output artifact"})

    artifact = store.get_artifact(import_rs.output_artifact_ids[0])
    if artifact is None:
        raise HTTPException(status_code=500, detail={"code": "ARTIFACT_NOT_FOUND", "message": "Import artifact not found in store"})

    # Forward the same import params to the pathway's import step
    # so the pathway re-import uses the same format/delimiter/header/schema settings.
    pathway_extra: dict[str, object] = {}
    if body.format and body.format != "auto":
        pathway_extra["format"] = body.format
    if body.delimiter is not None:
        pathway_extra["delimiter"] = body.delimiter
    if not body.has_header:
        pathway_extra["has_header"] = False
    if body.schema_overrides:
        pathway_extra["schema_overrides"] = dict(body.schema_overrides)
    if body.max_rows is not None:
        pathway_extra["max_rows"] = body.max_rows
    if body.encoding is not None:
        pathway_extra["encoding"] = body.encoding
    if body.null_values:
        pathway_extra["null_values"] = list(body.null_values)
    update_plan_import_params(
        store, body.project_id, str(source.resolve()),
        extra_params=pathway_extra or None,
    )

    return ArtifactResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        role=artifact.role,
        path=artifact.path,
        physical_hash=artifact.physical_hash,
        logical_hash=artifact.logical_hash,
        media_type=artifact.media_type,
        created_at=artifact.created_at,
        metadata={
            "row_count": artifact.metadata.get("row_count", 0),
            "column_count": artifact.metadata.get("column_count", 0),
        },
    )
