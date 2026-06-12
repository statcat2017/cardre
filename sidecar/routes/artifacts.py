"""Artifact retrieval endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from sidecar.models import ArtifactResponse
from sidecar.routes.projects import _load_registry

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _scan_all_stores():
    registry = _load_registry()
    for pid, entry in registry.items():
        from cardre.store import ProjectStore
        store = ProjectStore(Path(entry["path"]))
        yield pid, store


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str):
    for pid, store in _scan_all_stores():
        artifact = store.get_artifact(artifact_id)
        if artifact is not None:
            return ArtifactResponse(
                artifact_id=artifact.artifact_id,
                artifact_type=artifact.artifact_type,
                role=artifact.role,
                path=artifact.path,
                physical_hash=artifact.physical_hash,
                logical_hash=artifact.logical_hash,
                media_type=artifact.media_type,
                created_at=artifact.metadata.get("created_at", ""),
                metadata=artifact.metadata,
            )
    raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": f"No artifact with ID {artifact_id}"})
