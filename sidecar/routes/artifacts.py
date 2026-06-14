"""Artifact retrieval, summary, and preview endpoints — thin route handlers."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from cardre.services.artifact_service import (
    build_json_summary_preview,
    build_parquet_preview,
    find_artifact,
)
from sidecar.models import (
    ArtifactResponse,
    ArtifactSummaryResponse,
    ArtifactPreviewResponse,
    ColumnInfo,
)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str):
    artifact, _ = find_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": f"No artifact with ID {artifact_id}"})

    return ArtifactResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        role=artifact.role,
        path=artifact.path,
        physical_hash=artifact.physical_hash,
        logical_hash=artifact.logical_hash,
        media_type=artifact.media_type,
        created_at=artifact.created_at,
        metadata=artifact.metadata,
    )


@router.get("/{artifact_id}/summary", response_model=ArtifactSummaryResponse)
def get_artifact_summary(artifact_id: str):
    artifact, store = find_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": f"No artifact with ID {artifact_id}"})

    row_count = artifact.metadata.get("row_count")
    column_count = artifact.metadata.get("column_count")

    summary_preview = None
    if artifact.media_type == "application/json":
        try:
            data = json.loads(store.artifact_path(artifact).read_bytes())
        except Exception:
            data = None
        summary_preview = build_json_summary_preview(data)

    return ArtifactSummaryResponse(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        role=artifact.role,
        media_type=artifact.media_type,
        logical_hash=artifact.logical_hash,
        physical_hash=artifact.physical_hash,
        row_count=row_count,
        column_count=column_count,
        summary_preview=summary_preview,
    )


@router.get("/{artifact_id}/preview", response_model=ArtifactPreviewResponse)
def get_artifact_preview(
    artifact_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    artifact, store = find_artifact(artifact_id)
    if artifact is None or store is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": f"No artifact with ID {artifact_id}"})

    artifact_path = store.artifact_path(artifact)

    if artifact.media_type == "application/json":
        try:
            content = json.loads(artifact_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail={"code": "PREVIEW_FAILED", "message": "Could not read JSON artifact"})

        if isinstance(content, dict) and len(str(content)) < 100_000:
            truncated = {k: content[k] for k in list(content.keys())[:limit]}
            return ArtifactPreviewResponse(
                artifact_id=artifact.artifact_id,
                media_type=artifact.media_type,
                json_content=truncated,
                limit=limit,
                offset=offset,
            )
        elif isinstance(content, list) and len(str(content)) < 100_000:
            return ArtifactPreviewResponse(
                artifact_id=artifact.artifact_id,
                media_type=artifact.media_type,
                rows=content[offset:offset + limit],
                limit=limit,
                offset=offset,
            )
        else:
            return ArtifactPreviewResponse(
                artifact_id=artifact.artifact_id,
                media_type=artifact.media_type,
                json_content={"note": "Large JSON — use summary endpoint", "top_keys": list(content.keys()) if isinstance(content, dict) else None},
                limit=limit,
                offset=offset,
            )

    if artifact.media_type == "application/vnd.apache.parquet":
        try:
            total_rows = artifact.metadata.get("row_count")
            preview = build_parquet_preview(artifact_path, offset, limit, total_rows)
            return ArtifactPreviewResponse(
                artifact_id=artifact.artifact_id,
                media_type=artifact.media_type,
                row_count=preview["total_rows"],
                column_count=len(preview["columns"]),
                columns=[ColumnInfo(name=c["name"], dtype=c["dtype"]) for c in preview["columns"]],
                rows=preview["rows"],
                limit=limit,
                offset=offset,
            )
        except Exception:
            raise HTTPException(status_code=400, detail={"code": "PREVIEW_FAILED", "message": "Could not read Parquet artifact"})

    return ArtifactPreviewResponse(
        artifact_id=artifact.artifact_id,
        media_type=artifact.media_type,
        json_content={"note": f"Preview not supported for media type {artifact.media_type}"},
    )
