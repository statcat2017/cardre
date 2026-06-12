"""Dataset import endpoint — routes through the executor for audit trail."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.audit import StepSpec, json_logical_hash
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.store import ProjectStore
from sidecar.models import ArtifactResponse, ImportDatasetRequest
from sidecar.routes.projects import _load_registry

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _get_store(project_id: str) -> ProjectStore:
    registry = _load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})
    return ProjectStore(Path(entry["path"]))


def _update_plan_import_params(store: ProjectStore, project_id: str, source_path: str) -> None:
    """Update the proof pathway's import step with the given source_path.

    Creates a new plan version so the import step knows which file to load.
    """
    plans = store.get_plans_for_project(project_id)
    if not plans:
        return
    plan_id = plans[0]["plan_id"]
    latest_pv_id = store.get_latest_plan_version_id(plan_id)
    if latest_pv_id is None:
        return

    steps = store.get_plan_version_steps(latest_pv_id)
    new_steps = []
    for s in steps:
        if s.step_id == "import":
            params = {"source_path": str(Path(source_path).resolve())}
            new_steps.append(StepSpec(
                step_id=s.step_id,
                node_type=s.node_type,
                node_version=s.node_version,
                category=s.category,
                params=params,
                params_hash=json_logical_hash(params),
                parent_step_ids=s.parent_step_ids,
                branch_label=s.branch_label,
                position=s.position,
            ))
        else:
            new_steps.append(s)

    store.create_plan_version(plan_id, new_steps, description="Import configured")


def _get_or_create_import_plan(store: ProjectStore, project_id: str) -> str:
    """Find or create a dedicated import plan (separate from proof pathway)."""
    plans = store.get_plans_for_project(project_id)
    for p in plans:
        if p["name"] == "__import__":
            return p["plan_id"]
    return store.create_plan(project_id, "__import__")


@router.post("/import", response_model=ArtifactResponse, status_code=201)
def import_dataset(body: ImportDatasetRequest):
    source = Path(body.source_path)
    if not source.exists():
        raise HTTPException(status_code=400, detail={"code": "FILE_NOT_FOUND", "message": f"Source file not found: {source}"})

    store = _get_store(body.project_id)
    proj = store.get_project(body.project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found"})

    # Use a dedicated hidden import plan, not the proof pathway plan
    import_plan_id = _get_or_create_import_plan(store, body.project_id)

    params = {"source_path": str(source.resolve())}
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

    # Update proof pathway's import params (creates new version of proof
    # pathway plan with the correct source_path, preserving all 6 steps)
    _update_plan_import_params(store, body.project_id, str(source.resolve()))

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
            "source_dataset_id": artifact.metadata.get("source_dataset_id", ""),
            "row_count": artifact.metadata.get("row_count", 0),
            "column_count": artifact.metadata.get("column_count", 0),
        },
    )
