"""Artifact retrieval, summary, and preview endpoints — thin route handlers."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from cardre.services.artifact_service import (
    build_parquet_preview,
)
from cardre.services.project_registry import get_store_for_project
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind
from sidecar.models import (
    ArtifactResponse,
    ArtifactSummaryResponse,
    ArtifactPreviewResponse,
    ColumnInfo,
)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _shape_value(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {
                field.name: _shape_value(getattr(value, field.name))
                for field in fields(value)
                if not field.name.startswith("_")
            },
        }
    if isinstance(value, dict):
        keys = list(value.keys())
        return {
            "type": "object",
            "key_count": len(keys),
            "keys": keys[:10],
        }
    if isinstance(value, list):
        item_types = sorted({type(item).__name__ for item in value[:10]})
        return {
            "type": "array",
            "item_count": len(value),
            "item_types": item_types,
        }
    if isinstance(value, tuple):
        item_types = sorted({type(item).__name__ for item in value[:10]})
        return {
            "type": "array",
            "item_count": len(value),
            "item_types": item_types,
        }
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def _json_artifact_preview(reader: ArtifactEvidenceReader, artifact_id: str, kind_name: str | None) -> dict[str, Any]:
    if kind_name:
        try:
            kind = EvidenceKind(kind_name)
        except ValueError:
            kind = None
        else:
            evidence = reader.read_optional(artifact_id, kind)
            if evidence is not None:
                shape = _shape_value(evidence)
                return {
                    "kind": kind.value,
                    "fields": shape.get("fields", shape),
                }

    return {
        "kind": kind_name or "unknown",
        "note": "Preview unavailable for untyped JSON artifact",
    }


@router.get("/project/{project_id}/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_project_artifact(project_id: str, artifact_id: str):
    store = get_store_for_project(project_id)
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": f"No artifact with ID {artifact_id} in project {project_id}"})
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


@router.get("/project/{project_id}/artifacts/{artifact_id}/summary", response_model=ArtifactSummaryResponse)
def get_project_artifact_summary(project_id: str, artifact_id: str):
    store = get_store_for_project(project_id)
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": f"No artifact with ID {artifact_id} in project {project_id}"})
    reader = ArtifactEvidenceReader(store)
    evidence_summary = reader.summarise_artifact(artifact_id)
    row_count = artifact.metadata.get("row_count")
    column_count = artifact.metadata.get("column_count")
    summary_preview = None
    if artifact.media_type == "application/json":
        summary_preview = _json_artifact_preview(reader, artifact_id, evidence_summary.kind)
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


@router.get("/project/{project_id}/artifacts/{artifact_id}/preview", response_model=ArtifactPreviewResponse)
def get_project_artifact_preview(
    project_id: str,
    artifact_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    store = get_store_for_project(project_id)
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": f"No artifact with ID {artifact_id} in project {project_id}"})
    artifact_path = store.artifact_path(artifact)  # cardre-allow-artifact-read: artifact-byte-download
    reader = ArtifactEvidenceReader(store)
    if artifact.media_type == "application/json":
        evidence_summary = reader.summarise_artifact(artifact_id)
        json_preview = _json_artifact_preview(reader, artifact_id, evidence_summary.kind)
        return ArtifactPreviewResponse(
            artifact_id=artifact.artifact_id,
            media_type=artifact.media_type,
            json_content=json_preview,
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
        except Exception as exc:
            raise HTTPException(status_code=400, detail={
                "code": "PREVIEW_FAILED",
                "message": f"Could not read Parquet artifact: {exc}",
                "context": {"artifact_id": artifact_id, "path": str(artifact_path)},
            })
    return ArtifactPreviewResponse(
        artifact_id=artifact.artifact_id,
        media_type=artifact.media_type,
        json_content={"note": f"Preview not supported for media type {artifact.media_type}"},
    )
