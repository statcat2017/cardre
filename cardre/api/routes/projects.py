"""Project listing and creation endpoints — thin handlers calling use cases."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_create_project, get_get_project, get_list_projects
from cardre.api.errors import translate_domain_error
from cardre.api.mappers import project_to_response
from cardre.api.schemas import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    UnavailableProjectResponse,
)
from cardre.domain.errors import CardreError

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
def list_projects(
    list_projects: Any = Depends(get_list_projects),
) -> ProjectListResponse:
    """List all registered projects from the registry."""
    projects, unavailable = list_projects()
    return ProjectListResponse(
        projects=[project_to_response(p) for p in projects],
        unavailable_projects=[
            UnavailableProjectResponse(**u) for u in unavailable
        ],
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    get_project: Any = Depends(get_get_project),
) -> ProjectResponse:
    """Get a single project by ID, resolved via the registry."""
    try:
        project = get_project(project_id)
        return project_to_response(project)
    except CardreError as exc:
        raise translate_domain_error(exc) from exc


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    body: ProjectCreateRequest,
    create_project: Any = Depends(get_create_project),
) -> ProjectResponse:
    """Create a new project by bootstrapping a fresh store at body.path."""
    try:
        project = create_project(name=body.name, path=body.path)
        return project_to_response(project)
    except CardreError as exc:
        raise translate_domain_error(exc) from exc
