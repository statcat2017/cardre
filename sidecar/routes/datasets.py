"""Dataset import endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes import ImportGermanCreditNode
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
    plan_rows = store._connect().execute(
        "SELECT plan_id FROM plans WHERE project_id = ? LIMIT 1", (project_id,)
    ).fetchall()
    if not plan_rows:
        return
    plan_id = plan_rows[0]["plan_id"]
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


@router.post("/import", response_model=ArtifactResponse, status_code=201)
def import_dataset(body: ImportDatasetRequest):
    source = Path(body.source_path)
    if not source.exists():
        raise HTTPException(status_code=400, detail={"code": "FILE_NOT_FOUND", "message": f"Source file not found: {source}"})

    store = _get_store(body.project_id)
    proj = store.get_project(body.project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found"})

    plan_row = store._connect().execute(
        "SELECT plan_id FROM plans WHERE project_id = ? LIMIT 1", (body.project_id,)
    ).fetchone()
    plan_version_id = store.get_latest_plan_version_id(plan_row["plan_id"]) if plan_row else "manual-import"

    params = {"source_path": str(source.resolve())}
    spec = StepSpec(
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
    ctx = ExecutionContext(
        store=store,
        run_id="api-import",
        plan_version_id=plan_version_id or "manual-import",
        step_spec=spec,
        parent_run_steps=[],
        input_artifacts=[],
        validated_params=params,
        runtime_metadata={},
    )
    node = ImportGermanCreditNode()
    output = node.run(ctx)
    artifact = output.artifacts[0]

    _update_plan_import_params(store, body.project_id, str(source.resolve()))

    return ArtifactResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        role=artifact.role,
        path=artifact.path,
        physical_hash=artifact.physical_hash,
        logical_hash=artifact.logical_hash,
        media_type=artifact.media_type,
        created_at=artifact.metadata.get("created_at", ""),
        metadata={
            "source_dataset_id": artifact.metadata.get("source_dataset_id", ""),
            "row_count": artifact.metadata.get("row_count", 0),
            "column_count": artifact.metadata.get("column_count", 0),
        },
    )
