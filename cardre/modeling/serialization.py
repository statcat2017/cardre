from __future__ import annotations

import hashlib
from typing import Any

from cardre.application.ports.artifact_store import (
    ArtifactReader,
    StagedArtifact,
    StagedArtifactWriter,
)
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind


def _compute_bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_estimator_artifact(
    writer: StagedArtifactWriter,
    *,
    estimator_bytes: bytes,
    estimator_format: str,
    stem: str,
    creating_run_id: str = "",
    creating_run_step_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> StagedArtifact:
    logical_hash = _compute_bytes_hash(estimator_bytes)

    artifact_meta: dict[str, Any] = {
        "estimator_format": estimator_format,
        "byte_count": len(estimator_bytes),
        "creating_run_id": creating_run_id,
        "creating_run_step_id": creating_run_step_id,
    }
    if metadata:
        artifact_meta.update(metadata)

    return writer.stage_bytes(
        role="model",
        kind=EvidenceKind.MODEL_ARTIFACT.value,
        data=estimator_bytes,
        media_type="application/octet-stream",
        logical_hash=logical_hash,
        metadata=artifact_meta,
    )


def read_estimator_artifact(
    reader: ArtifactReader,
    artifact: ArtifactRef,
    *,
    expected_logical_hash: str | None = None,
    trusted_only: bool = True,
) -> bytes:
    data = reader.read_bytes(artifact)

    actual_hash = _compute_bytes_hash(data)
    if expected_logical_hash and actual_hash != expected_logical_hash:
        raise ValueError(
            f"Estimator artifact hash mismatch: expected {expected_logical_hash!r}, "
            f"got {actual_hash!r}. The artifact may have been tampered with.",
        )

    if trusted_only:
        creating_run_id = artifact.metadata.get("creating_run_id", "")
        if not creating_run_id:
            raise ValueError(
                f"Estimator artifact {artifact.artifact_id!r} has no creating_run_id "
                "metadata. Refusing to load untrusted binary model. "
                "Set trusted_only=False to override, or ensure the artifact "
                "was created by a Cardre run.",
            )

    return data
