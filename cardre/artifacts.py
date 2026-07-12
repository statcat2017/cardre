"""Shared artifact writing helpers for Cardre nodes.

Centralizes artifact creation so scorecard nodes do not duplicate
artifact registration boilerplate.  Wraps the v2 ProjectStore +
ArtifactRepository.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import polars as pl

from cardre.domain.artifacts import (
    ArtifactRef,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.store import ProjectStore
from cardre.store.artifact_repo import ArtifactRepository


def _register_bytes_artifact(
    store: ProjectStore,
    *,
    bytes_writer: Callable[[], bytes],
    logical_hash: str,
    stem: str,
    extension: str,
    media_type: str,
    directory: str,
    artifact_type: str,
    role: str,
    metadata: dict[str, Any] | None = None,
) -> ArtifactRef:
    stored_path = store.root / directory / f"{logical_hash[:16]}-{stem}{extension}"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = stored_path.with_name(f".{stored_path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        data = bytes_writer()
        temp_path.write_bytes(data)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise
    temp_path.replace(stored_path)
    phys = physical_hash(stored_path)
    artifact = ArtifactRef(
        artifact_id=str(uuid.uuid4()),
        artifact_type=artifact_type,
        role=role,
        path=relative_path(stored_path, store.root),
        physical_hash=phys,
        logical_hash=logical_hash,
        media_type=media_type,
        metadata=metadata or {},
    )
    repo = ArtifactRepository(store)
    registered_id = repo.register(artifact)
    if registered_id != artifact.artifact_id:
        existing = repo.get(registered_id)
        if existing is not None:
            return existing
    return artifact


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
    """Write a JSON payload as a new artifact and register it in the store."""
    logical = json_logical_hash(payload)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return _register_bytes_artifact(
        store,
        bytes_writer=lambda: serialized,
        logical_hash=logical,
        stem=stem,
        extension=".json",
        media_type="application/json",
        directory=directory,
        artifact_type=artifact_type,
        role=role,
        metadata=metadata,
    )


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
    """Write a Polars DataFrame as a parquet artifact and register it."""
    logical = table_logical_hash(frame)
    return _register_bytes_artifact(
        store,
        bytes_writer=lambda: _parquet_bytes(frame),
        logical_hash=logical,
        stem=stem,
        extension=".parquet",
        media_type="application/vnd.apache.parquet",
        directory=directory,
        artifact_type=artifact_type,
        role=role,
        metadata=metadata,
    )


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
    import io
    buf = io.BytesIO()
    frame.write_parquet(buf, statistics=False, compression="zstd")
    return buf.getvalue()


def write_csv_artifact(
    store: ProjectStore,
    *,
    artifact_type: str,
    role: str,
    stem: str,
    frame: pl.DataFrame,
    metadata: dict[str, Any] | None = None,
    directory: str = "artifacts",
) -> ArtifactRef:
    """Write a Polars DataFrame as a CSV artifact and register it."""
    logical = table_logical_hash(frame)
    return _register_bytes_artifact(
        store,
        bytes_writer=lambda: _csv_bytes(frame),
        logical_hash=logical,
        stem=stem,
        extension=".csv",
        media_type="text/csv",
        directory=directory,
        artifact_type=artifact_type,
        role=role,
        metadata=metadata,
    )


def _csv_bytes(frame: pl.DataFrame) -> bytes:
    import io
    buf = io.BytesIO()
    frame.write_csv(buf)
    return buf.getvalue()


__all__ = [
    "_register_bytes_artifact",
    "write_csv_artifact",
    "write_json_artifact",
    "write_parquet_artifact",
]
