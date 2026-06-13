"""Artifact retrieval, summary, and preview endpoints."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from fastapi import APIRouter, HTTPException, Query

from sidecar.models import (
    ArtifactResponse,
    ArtifactSummaryResponse,
    ArtifactPreviewResponse,
    ColumnInfo,
)
from sidecar.routes.projects import _load_registry

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _scan_all_stores():
    registry = _load_registry()
    for pid, entry in registry.items():
        from cardre.store import ProjectStore
        store = ProjectStore(Path(entry["path"]))
        yield pid, store


def _find_artifact(artifact_id: str):
    for pid, store in _scan_all_stores():
        artifact = store.get_artifact(artifact_id)
        if artifact is not None:
            return artifact, store
    return None, None


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str):
    artifact, _ = _find_artifact(artifact_id)
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
    artifact, store = _find_artifact(artifact_id)
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

        if isinstance(data, dict):
            summary_preview = {k: data[k] for k in list(data.keys())[:10]}
            summary_preview["_key_count"] = len(data)
        elif isinstance(data, list):
            summary_preview = {"_item_count": len(data), "_first_items": data[:5]}
        elif data is not None:
            summary_preview = {"_value": str(data)[:500]}
        else:
            summary_preview = None

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
    artifact, store = _find_artifact(artifact_id)
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
            if total_rows is None:
                total_rows = pl.scan_parquet(artifact_path).select(pl.len()).collect().item()
            df = pl.scan_parquet(artifact_path).slice(offset, limit).collect()
            columns = [
                ColumnInfo(name=c, dtype=str(df.schema[c]))
                for c in df.columns
            ]
            rows = df.to_dicts()
            return ArtifactPreviewResponse(
                artifact_id=artifact.artifact_id,
                media_type=artifact.media_type,
                row_count=total_rows,
                column_count=len(columns),
                columns=columns,
                rows=rows,
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
