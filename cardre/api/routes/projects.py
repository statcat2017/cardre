"""Project listing and detail endpoints.

These endpoints use the project registry directly — they do not require
X-Project-Id or X-Project-Path headers. The registry maps project_id to
project root; the route resolves the root, opens a store, and returns
metadata.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from cardre._version import __version__
from cardre.api.errors import (
    INVALID_PROJECT_PATH,
    PROJECT_NOT_FOUND,
    STORE_ALREADY_EXISTS,
    CardreApiError,
)
from cardre.api.schemas import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    UnavailableProjectResponse,
)
from cardre.config import CardreConfig
from cardre.domain.errors import SchemaVersionError
from cardre.services.project_resolver import ProjectResolver
from cardre.store.db import ProjectStore
from cardre.store.project_repo import ProjectRepository

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects() -> ProjectListResponse:
    """List all registered projects from the registry.

    Projects that cannot be opened (corrupt store, missing root, schema
    mismatch) are reported in ``unavailable_projects`` rather than
    silently skipped.
    """
    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    registry = resolver.list_projects()
    projects = []
    unavailable = []
    for project_id, root_str in registry.items():
        root = Path(root_str)
        if not root.exists():
            unavailable.append(
                UnavailableProjectResponse(
                    project_id=project_id,
                    root=root_str,
                    code="PROJECT_ROOT_MISSING",
                    message=f"Project root {root_str} does not exist.",
                )
            )
            continue
        store = ProjectStore(root)
        try:
            store.open()
            repo = ProjectRepository(store)
            p = repo.get(project_id)
            if p is not None:
                projects.append(
                    ProjectResponse(
                        project_id=p["project_id"],
                        name=p["name"],
                        created_at=p["created_at"],
                        cardre_version=p.get("cardre_version", __version__),
                    )
                )
            else:
                unavailable.append(
                    UnavailableProjectResponse(
                        project_id=project_id,
                        root=root_str,
                        code="PROJECT_METADATA_MISSING",
                        message=f"Project {project_id!r} not found in store at {root_str}.",
                    )
                )
        except Exception as exc:
            unavailable.append(
                UnavailableProjectResponse(
                    project_id=project_id,
                    root=root_str,
                    code="PROJECT_OPEN_FAILED",
                    message=str(exc),
                )
            )
        finally:
            store.close()
    return ProjectListResponse(projects=projects, unavailable_projects=unavailable)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    """Get a single project by ID, resolved via the registry."""
    resolver = ProjectResolver(CardreConfig.from_env().registry_path)
    root = resolver.resolve_root(project_id)
    store = ProjectStore(root)
    try:
        store.open()
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
            cardre_version=project.get("cardre_version", __version__),
        )
    finally:
        store.close()


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest,
) -> ProjectResponse:
    """Create a new project by bootstrapping a fresh v2 store at body.path."""
    root = Path(body.path)
    if not root.is_absolute():
        raise CardreApiError(
            code=INVALID_PROJECT_PATH,
            message=f"Project path must be absolute, got {body.path!r}.",
            status_code=400,
        )
    if ".." in root.parts:
        raise CardreApiError(
            code=INVALID_PROJECT_PATH,
            message=f"Project path must not contain '..' traversal, got {body.path!r}.",
            status_code=400,
        )
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
        ProjectResolver(CardreConfig.from_env().registry_path).register_project(project_id, root)
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
