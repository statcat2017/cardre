"""Project listing and detail endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.errors import CardreApiError, PROJECT_NOT_FOUND, STORE_ALREADY_EXISTS
from cardre.api.schemas import ProjectCreateRequest, ProjectListResponse, ProjectResponse
from cardre.domain.errors import SchemaVersionError
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
        raise CardreApiError(
            code=PROJECT_NOT_FOUND,
            message=f"Project {project_id!r} not found.",
            status_code=404,
        )
    return ProjectResponse(
        project_id=project["project_id"],
        name=project["name"],
        created_at=project["created_at"],
        cardre_version=project.get("cardre_version", "0.2.0"),
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest,
) -> ProjectResponse:
    """Create a new project by bootstrapping a fresh v2 store at body.path."""
    root = Path(body.path)
    store = ProjectStore(root)
    try:
        store.initialize()
    except SchemaVersionError as e:
        raise CardreApiError(
            code=STORE_ALREADY_EXISTS,
            message=str(e),
            status_code=409,
        )
    try:
        repo = ProjectRepository(store)
        project_id = repo.create(name=body.name)
        project = repo.get(project_id)
        assert project is not None
        return ProjectResponse(
            project_id=project["project_id"],
            name=project["name"],
            created_at=project["created_at"],
            cardre_version=project.get("cardre_version", "0.2.0"),
        )
    finally:
        store.close()
