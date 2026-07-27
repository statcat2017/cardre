"""Artifact endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cardre.api.dependencies import get_container
from cardre.api.errors import CardreApiError, ErrorCode
from cardre.api.mappers import artifact_to_response
from cardre.api.schemas import ArtifactResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["artifacts"])


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(project_id: str, artifact_id: str, container=Depends(get_container)):
    with container.uow_factory.read_only(project_id) as uow:
        art = uow.artifacts.get(artifact_id)
    if art is None:
        raise CardreApiError(code=ErrorCode.ARTIFACT_NOT_FOUND, message=f"Artifact {artifact_id!r} not found.", status_code=404)
    return artifact_to_response(art)
