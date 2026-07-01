"""Project listing and detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cardre.api.schemas import ProjectListResponse, ProjectResponse
from cardre.api.dependencies import get_project_store
from cardre.store.db import ProjectStore
from cardre.store.project_repo import ProjectRepository

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    store: ProjectStore = Depends(get_project_store),
) -> ProjectListResponse:
    """List all projects (from the currently opened store)."""
    repo = ProjectRepository(store)
    projects = repo.list_all()
    return ProjectListResponse(
        projects=[
            ProjectResponse(
                project_id=p["project_id"],
                name=p["name"],
                created_at=p["created_at"],
                cardre_version=p.get("cardre_version", "0.2.0"),
            )
            for p in projects
        ]
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ProjectResponse:
    """Get a single project by ID."""
    repo = ProjectRepository(store)
    project = repo.get(project_id)
    if project is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PROJECT_NOT_FOUND",
                "message": f"Project {project_id!r} not found.",
            },
        )
    return ProjectResponse(
        project_id=project["project_id"],
        name=project["name"],
        created_at=project["created_at"],
        cardre_version=project.get("cardre_version", "0.2.0"),
    )
