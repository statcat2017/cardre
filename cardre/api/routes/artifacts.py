"""Artifact endpoints — project-scoped artifact access."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_project_store
from cardre.api.errors import ARTIFACT_NOT_FOUND, CardreApiError
from cardre.api.schemas import ArtifactResponse
from cardre.store.artifact_repo import ArtifactRepository
from cardre.store.db import ProjectStore

router = APIRouter(prefix="/projects/{project_id}", tags=["artifacts"])


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    project_id: str,
    artifact_id: str,
    store: ProjectStore = Depends(get_project_store),
) -> ArtifactResponse:
    """Get a single artifact by ID, scoped to the project."""
    repo = ArtifactRepository(store)
    artifact = repo.get_for_project(project_id, artifact_id)
    if artifact is None:
        raise CardreApiError(
            code=ARTIFACT_NOT_FOUND,
            message=f"Artifact {artifact_id!r} not found in project {project_id!r}.",
            status_code=404,
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
    )
