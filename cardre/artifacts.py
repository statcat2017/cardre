"""Shared artifact writing helpers for Cardre nodes.

Centralizes artifact creation so scorecard nodes do not duplicate
artifact registration boilerplate.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
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
    stored_path.write_bytes(serialized)
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
    buf = io.BytesIO()
    frame.write_parquet(buf, statistics=False, compression="zstd")
    parquet_bytes = buf.getvalue()
    filename = f"{logical[:16]}-{stem}.parquet"
    stored_path = store.root / directory / filename
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(parquet_bytes)
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


def make_fingerprint(
    plan_version_id: str,
    step_id: str,
    node_type: str,
    node_version: str,
    params_hash: str,
    parent_run_steps: list,
    input_artifacts: list[ArtifactRef],
    output_artifacts: list[ArtifactRef],
) -> dict[str, Any]:
    parent_outputs: dict[str, list[str]] = {}
    for rs in parent_run_steps:
        parent_outputs[rs.step_id] = rs.execution_fingerprint.get(
            "output_artifact_logical_hashes", []
        )
    return {
        "plan_version_id": plan_version_id,
        "step_id": step_id,
        "node_type": node_type,
        "node_version": node_version,
        "params_hash": params_hash,
        "parent_run_step_ids": [rs.run_step_id for rs in parent_run_steps],
        "input_artifact_logical_hashes": [a.logical_hash for a in input_artifacts],
        "output_artifact_logical_hashes": [a.logical_hash for a in output_artifacts],
        "parent_output_logical_hashes_by_step": parent_outputs,
    }
