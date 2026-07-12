"""Secure estimator serialization for binary model artifacts.

Provides write and read helpers that enforce artifact-store provenance,
hash verification, and untrusted-load guards. Binary estimators (sklearn
pickles, joblib, etc.) are treated as untrusted serialized objects by
default.
"""

from __future__ import annotations

import hashlib
from typing import Any

from cardre.artifacts import _register_bytes_artifact
from cardre.domain.artifacts import ArtifactRef
from cardre.store import ProjectStore


def _compute_bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_estimator_artifact(
    store: ProjectStore,
    *,
    estimator_bytes: bytes,
    estimator_format: str,
    stem: str,
    creating_run_id: str = "",
    creating_run_step_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> ArtifactRef:
    """Write a binary estimator artifact to the project store.

    Records physical hash, format, and provenance. The estimator bytes
    are stored in the ``artifacts`` directory alongside JSON artifacts.
    Uses the shared ``_register_bytes_artifact`` helper for temp-file
    atomicity and dedup-return.
    """
    logical_hash = _compute_bytes_hash(estimator_bytes)
    extension = {
        "pickle": ".pkl",
        "joblib": ".joblib",
        "skops": ".skops",
        "onnx": ".onnx",
    }.get(estimator_format, ".bin")

    artifact_meta: dict[str, Any] = {
        "estimator_format": estimator_format,
        "byte_count": len(estimator_bytes),
        "creating_run_id": creating_run_id,
        "creating_run_step_id": creating_run_step_id,
    }
    if metadata:
        artifact_meta.update(metadata)

    return _register_bytes_artifact(
        store,
        bytes_writer=lambda: estimator_bytes,
        logical_hash=logical_hash,
        stem=stem,
        extension=extension,
        media_type="application/octet-stream",
        directory="artifacts",
        artifact_type="estimator",
        role="model",
        metadata=artifact_meta,
    )


def read_estimator_artifact(
    store: ProjectStore,
    artifact: ArtifactRef,
    *,
    expected_logical_hash: str | None = None,
    trusted_only: bool = True,
) -> bytes:
    """Read a binary estimator artifact with verification.

    Parameters
    ----------
    store : ProjectStore
        The project store containing the artifact.
    artifact : ArtifactRef
        The artifact reference to read.
    expected_logical_hash : str, optional
        If provided, verifies the artifact bytes match this hash.
    trusted_only : bool
        If True (default), refuses to load artifacts that were not created
        by Cardre (i.e., have no ``creating_run_id`` in metadata). Set to
        False to allow loading external binary models with a warning.

    Returns
    -------
    bytes
        The raw estimator bytes.

    Raises
    ------
    ValueError
        If hash verification fails or the artifact is from an untrusted
        source and trusted_only is True.
    """
    art_path = store.artifact_path(artifact)  # cardre-allow-artifact-read: low-level-evidence-parser

    if not art_path.exists():
        raise ValueError(
            f"Estimator artifact file not found: {art_path}"
        )

    data = art_path.read_bytes()

    actual_hash = _compute_bytes_hash(data)
    if expected_logical_hash and actual_hash != expected_logical_hash:
        raise ValueError(
            f"Estimator artifact hash mismatch: expected {expected_logical_hash!r}, "
            f"got {actual_hash!r}. The artifact may have been tampered with."
        )

    if trusted_only:
        creating_run_id = artifact.metadata.get("creating_run_id", "")
        if not creating_run_id:
            raise ValueError(
                f"Estimator artifact {artifact.artifact_id!r} has no creating_run_id "
                "metadata. Refusing to load untrusted binary model. "
                "Set trusted_only=False to override, or ensure the artifact "
                "was created by a Cardre run."
            )

    return data
