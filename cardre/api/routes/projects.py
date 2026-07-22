"""Project listing and creation endpoints — thin handlers calling use cases."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_create_project, get_get_project, get_list_projects
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.routes._run_mappings import project_to_response
from cardre.api.schemas import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    UnavailableProjectResponse,
)
from cardre.domain.errors import CardreError

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
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
async def get_project(
    project_id: str,
    get_project: Any = Depends(get_get_project),
) -> ProjectResponse:
    """Get a single project by ID, resolved via the registry."""
    try:
        project = get_project(project_id)
        return project_to_response(project)
    except CardreError as exc:
        if exc.code == "PROJECT_NOT_FOUND":
            raise CardreApiError(
                code=ErrorCode.PROJECT_NOT_FOUND,
                message=f"Project {project_id!r} not found.",
                status_code=404,
            ) from exc
        raise


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest,
    create_project: Any = Depends(get_create_project),
) -> ProjectResponse:
    """Create a new project by bootstrapping a fresh store at body.path."""
    try:
        project = create_project(name=body.name, path=body.path)
        return project_to_response(project)
    except CardreError as exc:
        if exc.code == "INVALID_PROJECT_PATH":
            raise CardreApiError(
                code=ErrorCode.INVALID_PROJECT_PATH,
                message=str(exc),
                status_code=400,
            ) from exc
        if exc.code in ("STORE_ALREADY_EXISTS", "STORE_VERSION_INCOMPATIBLE"):
            raise CardreApiError(
                code=ErrorCode.STORE_ALREADY_EXISTS,
                message=str(exc),
                status_code=409,
            ) from exc
        raise
