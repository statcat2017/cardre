"""Project management endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from cardre.store import ProjectStore
from sidecar.models import (
    CreateProjectRequest,
    ProjectDetailResponse,
    ProjectResponse,
)
from sidecar.proof_pathway import register_proof_pathway

router = APIRouter(prefix="/projects", tags=["projects"])

REGISTRY_PATH = Path.home() / ".cardre" / "projects.json"


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {}


def _save_registry(registry: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(body: CreateProjectRequest):
    path = Path(body.path)
    if path.exists():
        if (path / "cardre.sqlite").exists():
            raise HTTPException(
                status_code=409,
                detail={"code": "PROJECT_EXISTS", "message": f"A Cardre project already exists at {path}"},
            )
        else:
            raise HTTPException(
                status_code=409,
                detail={"code": "DIR_EXISTS", "message": f"Directory {path} exists but is not a Cardre project"},
            )

    store = ProjectStore(path)
    store.initialize()
    project_id = store.create_project(body.name)

    registry = _load_registry()
    registry[project_id] = {"path": str(path.resolve()), "name": body.name}
    _save_registry(registry)

    register_proof_pathway(store, project_id)

    return ProjectResponse(
        project_id=project_id,
        path=str(path.resolve()),
        name=body.name,
        created_at=store.get_project(project_id)["created_at"],
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: str):
    registry = _load_registry()
    entry = registry.get(project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": f"No project with ID {project_id}"})

    path = Path(entry["path"])
    if not (path / "cardre.sqlite").exists():
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project directory no longer exists"})

    store = ProjectStore(path)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found in SQLite"})

    plans = store._connect().execute(
        "SELECT COUNT(*) FROM plans WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    runs = store._connect().execute(
        "SELECT COUNT(*) FROM runs r JOIN plan_versions pv ON r.plan_version_id = pv.plan_version_id "
        "JOIN plans p ON pv.plan_id = p.plan_id WHERE p.project_id = ?", (project_id,)
    ).fetchone()[0]

    return ProjectDetailResponse(
        project_id=proj["project_id"],
        path=str(path),
        name=proj["name"],
        created_at=proj["created_at"],
        plan_count=plans,
        run_count=runs,
    )
