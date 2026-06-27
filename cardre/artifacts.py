"""Shared artifact writing helpers for Cardre nodes.

Centralizes artifact creation so scorecard nodes do not duplicate
artifact registration boilerplate.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import polars as pl

from cardre.audit import (
    ArtifactRef,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.store import ProjectStore


def write_json_artifact(
    store: ProjectStore,
    *,
    artifact_type: str,
    role: str,
    stem: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    directory: str = "artifacts",
) -> ArtifactRef:
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    logical = json_logical_hash(payload)
    filename = f"{logical[:16]}-{stem}.json"
    stored_path = store.root / directory / filename
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = stored_path.with_name(f".{stored_path.name}.{uuid.uuid4().hex[:8]}.tmp")
    temp_path.write_bytes(serialized)
    temp_path.replace(stored_path)
    phys = physical_hash(stored_path)
    artifact = ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type=artifact_type,
        role=role,
        path=relative_path(stored_path, store.root),
        physical_hash=phys,
        logical_hash=logical,
        media_type="application/json",
        metadata=metadata or {},
    )
    store.register_artifact(artifact)
    return artifact


def write_parquet_artifact(
    store: ProjectStore,
    *,
    artifact_type: str,
    role: str,
    stem: str,
    frame: pl.DataFrame,
    metadata: dict[str, Any] | None = None,
    directory: str = "datasets",
) -> ArtifactRef:
    logical = table_logical_hash(frame)
    filename = f"{logical[:16]}-{stem}.parquet"
    stored_path = store.root / directory / filename
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = stored_path.with_name(f".{stored_path.name}.{uuid.uuid4().hex[:8]}.tmp")
    # Stream directly to the temp file path — avoids buffering the entire
    # parquet in memory, reducing peak memory for large DataFrames.
    try:
        frame.write_parquet(temp_path, statistics=False, compression="zstd")
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    temp_path.replace(stored_path)
    phys = physical_hash(stored_path)
    artifact_meta = {
        "row_count": frame.height,
        "column_count": frame.width,
        "schema": {c: str(frame.schema[c]) for c in frame.columns},
    }
    if metadata:
        artifact_meta.update(metadata)
    artifact = ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type=artifact_type,
        role=role,
        path=relative_path(stored_path, store.root),
        physical_hash=phys,
        logical_hash=logical,
        media_type="application/vnd.apache.parquet",
        metadata=artifact_meta,
    )
    store.register_artifact(artifact)
    return artifact



