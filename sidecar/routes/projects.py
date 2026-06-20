"""Project management endpoints — thin wrappers over service layer."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.services.project_registry import (
    create_project_registry_entry,
    get_entry,
    get_store_for_project,
    load_registry,
    project_path_exists,
    validate_project_path,
)
from cardre.store import ProjectStore
from sidecar.models import (
    CreateProjectRequest,
    PlanListItem,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectListItem,
    ProjectPlansResponse,
    ProjectResponse,
    ProjectRunsResponse,
    RunListItem,
    ProjectArtifactsResponse,
    ArtifactListItem,
)
from sidecar.proof_pathway import register_proof_pathway, register_reject_inference_pathway, register_scorecard_pathway

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(body: CreateProjectRequest):
    path = Path(body.path).resolve()

    try:
        validate_project_path(path)
    except ValueError as exc:
        msg = str(exc)
        code = msg.split(":")[0] if ":" in msg else "INVALID_PATH"
        status_code = 409 if code in ("PROJECT_EXISTS", "DIR_EXISTS") else 400
        raise HTTPException(status_code=status_code, detail={"code": code, "message": msg})

    if not body.name.strip():
        raise HTTPException(status_code=400, detail={"code": "INVALID_NAME", "message": "Project name must not be empty"})

    store = ProjectStore(path)
    store.initialize()
    project_id = store.create_project(body.name)

    create_project_registry_entry(project_id, path, body.name)

    register_proof_pathway(store, project_id)
    register_scorecard_pathway(store, project_id)
    register_reject_inference_pathway(store, project_id)

    return ProjectResponse(
        project_id=project_id,
        path=str(path.resolve()),
        name=body.name,
        created_at=store.get_project(project_id)["created_at"],
    )


@router.get("", response_model=ProjectListResponse)
def list_projects():
    registry = load_registry()
    items = []
    missing = 0
    for pid, entry in registry.items():
        exists = project_path_exists(pid)
        if not exists:
            missing += 1
        items.append(ProjectListItem(
            project_id=pid,
            name=entry.get("name", ""),
            path=entry.get("path", ""),
            path_exists=exists,
        ))
    return ProjectListResponse(
        projects=items,
        total_count=len(items),
        missing_path_count=missing,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: str):
    entry = get_entry(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})

    store = get_store_for_project(project_id)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found in SQLite"})

    plans = len(store.get_plans_for_project(project_id))
    runs = len(store.list_runs())

    return ProjectDetailResponse(
        project_id=proj["project_id"],
        path=str(Path(entry["path"])),
        name=proj["name"],
        created_at=proj["created_at"],
        plan_count=plans,
        run_count=runs,
    )


@router.get("/{project_id}/plans", response_model=ProjectPlansResponse)
def get_project_plans(project_id: str):
    entry = get_entry(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})

    store = get_store_for_project(project_id)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found in SQLite"})

    raw_plans = store.get_plans_for_project(project_id)
    plan_items = []
    for p in raw_plans:
        plan_id = p["plan_id"]
        name = p["name"]
        is_hidden = name == "__import__"
        is_default = name == "Scorecard Pathway"
        latest_pv_id = store.get_latest_plan_version_id(plan_id)
        if latest_pv_id is None:
            continue
        plan_items.append(PlanListItem(
            plan_id=plan_id,
            name=name,
            latest_version_id=latest_pv_id,
            is_default=is_default,
            is_hidden=is_hidden,
        ))

    visible_plans = [p for p in plan_items if not p.is_hidden]

    return ProjectPlansResponse(
        project_id=project_id,
        plans=visible_plans,
    )


@router.get("/{project_id}/runs", response_model=ProjectRunsResponse)
def get_project_runs(project_id: str):
    store = get_store_for_project(project_id)
    runs = store.list_runs_for_project(project_id)

    items = []
    for r in runs:
        pv_id = r["plan_version_id"]
        step_count = r.get("step_count", 0)
        items.append(RunListItem(
            run_id=r["run_id"],
            plan_version_id=pv_id,
            status=r["status"],
            started_at=r["started_at"],
            finished_at=r.get("finished_at"),
            step_count=step_count,
        ))

    return ProjectRunsResponse(project_id=project_id, runs=items)


@router.get("/{project_id}/artifacts", response_model=ProjectArtifactsResponse)
def get_project_artifacts(
    project_id: str,
    role: str | None = None,
    artifact_type: str | None = None,
    producing_step_id: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    store = get_store_for_project(project_id)
    artifacts = store.list_artifacts_for_project(project_id)

    if role:
        artifacts = [a for a in artifacts if a.role == role]
    if artifact_type:
        artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
    if producing_step_id:
        artifact_ids = store.get_artifact_ids_for_producing_step(producing_step_id)
        artifacts = [a for a in artifacts if a.artifact_id in artifact_ids]
    if run_id:
        artifact_ids = store.get_artifact_ids_for_run(run_id)
        artifacts = [a for a in artifacts if a.artifact_id in artifact_ids]

    artifacts = artifacts[offset:offset + limit]

    items = [
        ArtifactListItem(
            artifact_id=a.artifact_id,
            artifact_type=a.artifact_type,
            role=a.role,
            path=a.path,
            physical_hash=a.physical_hash,
            logical_hash=a.logical_hash,
            media_type=a.media_type,
            created_at=a.created_at,
            metadata=a.metadata,
        )
        for a in artifacts
    ]

    return ProjectArtifactsResponse(project_id=project_id, artifacts=items)
