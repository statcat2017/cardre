"""Model-artifact publication and loading — the deep module at the estimator seam.

A fitted estimator (or calibrator) is published as **two** Artifacts sharing
one descriptor family: a parseable JSON ``model`` and a joblib-serialized
``estimator`` binary. ``publish_estimator`` serialises the estimator, computes
the dual hash and the descriptor id the store will assign, and returns an
``EstimatorRef`` the caller cites in the model JSON *before* the binary is
staged. ``stage_estimator_bytes`` then stages the binary under that same
descriptor. ``load_estimator`` is the inverse: resolve the reference, verify
the hash and provenance, and deserialise.

The JSON-must-precede-bytes ordering and the mandatory load verification are
interface facts of this module (see CONTEXT.md "Estimator Reference" and
ADR-0016), not conventions each node re-implements.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import joblib

from cardre.domain.artifacts import descriptor_id
from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import InputCollection, OutputPublisher

ESTIMATOR_ROLE = "estimator"
ESTIMATOR_MEDIA_TYPE = "application/octet-stream"
_SHA256_HEX_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class EstimatorRef:
    """The pre-publication reference a model JSON cites for its estimator binary.

    ``provisional_artifact_id`` is the deterministic descriptor id the store
    will assign when the binary is staged, so the JSON model can reference the
    binary before it exists on disk. ``bytes`` is the serialized payload the
    caller stages via :func:`stage_estimator_bytes`.
    """

    provisional_artifact_id: str
    logical_hash: str
    physical_hash: str
    bytes: bytes
    metadata: JsonDict


def estimator_descriptor_id(data: bytes, logical_hash: str, metadata: JsonDict) -> str:
    """Compute the descriptor id the store assigns to a binary estimator.

    Mirrors the store's ``FsArtifactStore._stage`` computation for the
    ``estimator`` role so the id computed here matches the id the store derives
    at publication time (see CONTEXT.md "Estimator Reference"). Test adapters
    use this to mirror the store when they record a ``publish_bytes`` call.
    """
    kind_value = EvidenceKind.MODEL_ARTIFACT.value
    return descriptor_id(
        artifact_type=kind_value.split(".")[-1] if "." in kind_value else kind_value,
        role=ESTIMATOR_ROLE,
        media_type=ESTIMATOR_MEDIA_TYPE,
        kind=kind_value,
        schema_version=str(metadata.get("schema_version", "")),
        logical_hash=logical_hash,
        physical_hash=hashlib.sha256(data).hexdigest(),
        metadata=metadata,
    )


def publish_estimator(
    estimator: Any,
    *,
    step_id: str,
    run_id: str,
    model_family: str | None = None,
    metadata: JsonDict | None = None,
) -> EstimatorRef:
    """Serialise *estimator* and return an ``EstimatorRef`` the model JSON cites.

    The binary is *not* published here — the caller publishes the JSON model
    first (citing ``EstimatorRef.provisional_artifact_id``), then calls
    :func:`stage_estimator_bytes`. *metadata* is merged over the base estimator
    metadata (e.g. ``schema_version``, ``artifact_subtype`` for a calibrator).
    ``model_family`` is added to the metadata (and thus participates in the
    descriptor identity) only when supplied — a calibrator that historically
    carried no ``model_family`` field keeps its identity unchanged.
    """
    buf = io.BytesIO()
    joblib.dump(estimator, buf)
    estimator_bytes = buf.getvalue()
    logical_hash = hashlib.sha256(estimator_bytes).hexdigest()

    merged: JsonDict = {
        "estimator_format": "joblib",
        "byte_count": len(estimator_bytes),
        "creating_run_id": run_id,
        "creating_run_step_id": step_id,
    }
    if model_family is not None:
        merged["model_family"] = model_family
    if metadata:
        merged.update(metadata)

    return EstimatorRef(
        provisional_artifact_id=estimator_descriptor_id(estimator_bytes, logical_hash, merged),
        logical_hash=logical_hash,
        physical_hash=logical_hash,
        bytes=estimator_bytes,
        metadata=merged,
    )


def stage_estimator_bytes(outputs: OutputPublisher, ref: EstimatorRef) -> Any:
    """Stage the estimator binary under the descriptor id *ref* already carries."""
    return outputs.publish_bytes(
        role=ESTIMATOR_ROLE,
        kind=EvidenceKind.MODEL_ARTIFACT,
        data=ref.bytes,
        media_type=ESTIMATOR_MEDIA_TYPE,
        logical_hash=ref.logical_hash,
        metadata=ref.metadata,
    )


def load_estimator(
    inputs: InputCollection,
    estimator_reference: Mapping[str, Any],
    *,
    node_type: str = "",
) -> Any | None:
    """Resolve, verify and deserialise the estimator a model JSON references.

    Returns ``None`` when no reference is embedded or the referenced artifact
    is not among the step's inputs. Raises ``ValueError`` when the reference
    lacks a valid SHA-256 ``logical_hash``, when the bytes fail hash
    verification, or when the artifact lacks ``creating_run_id`` provenance.
    Load verification is mandatory and there is no unverified path (ADR-0016):
    a missing ``logical_hash`` is rejected *before* any bytes are read or
    deserialised.
    """
    artifact_id = estimator_reference.get("artifact_id", "")
    if not artifact_id:
        return None

    expected_hash = estimator_reference.get("logical_hash") or ""
    if not _is_sha256_hex(expected_hash):
        raise ValueError(
            f"Estimator reference for artifact {artifact_id!r} carries an invalid "
            f"or missing logical_hash ({expected_hash!r}); refusing to load an "
            "unverifiable binary (ADR-0016)."
        )

    physical_hash = estimator_reference.get("physical_hash") or None
    estimator_art = inputs.artifact_ref(artifact_id, physical_hash=physical_hash)
    if estimator_art is None:
        return None

    estimator_bytes = inputs.read_bytes(estimator_art)
    actual_hash = hashlib.sha256(estimator_bytes).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(
            f"Estimator artifact hash mismatch: expected {expected_hash!r}, "
            f"got {actual_hash!r}. The artifact may have been tampered with."
        )

    provenance = getattr(estimator_art, "metadata", {})
    if not provenance.get("creating_run_id", ""):
        raise ValueError(
            f"Estimator artifact {artifact_id!r} has no creating_run_id metadata. "
            "Refusing to load untrusted binary model."
        )

    return joblib.load(io.BytesIO(estimator_bytes))


def _is_sha256_hex(value: str) -> bool:
    """True when *value* is a 64-character lowercase hex SHA-256 digest."""
    return (
        len(value) == _SHA256_HEX_LENGTH
        and all(ch in _HEX_DIGITS for ch in value)
        and value == value.lower()
    )


__all__ = [
    "ESTIMATOR_MEDIA_TYPE",
    "ESTIMATOR_ROLE",
    "EstimatorRef",
    "estimator_descriptor_id",
    "load_estimator",
    "publish_estimator",
    "stage_estimator_bytes",
]
