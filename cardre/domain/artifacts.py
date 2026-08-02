"""Artifact data structures and hashing utilities — domain kernel.

No I/O, no nodes, no store.  Pure functions and frozen dataclasses only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cardre.domain.diagnostics import JsonDict

CHUNK_SIZE = 1024 * 1024


def relative_path(path: Path, root: Path) -> str:
    """Return the relative POSIX path of *path* under *root*."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def physical_hash(path: Path) -> str:
    """SHA-256 of raw file bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_logical_hash(data: JsonDict) -> str:
    """SHA-256 of the canonical JSON representation (sorted-keys, no spaces)."""
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


TABLE_LOGICAL_HASH_VERSION = "v3"


def table_logical_hash(table: Any) -> str:
    """SHA-256 of a sorted-column canonical Parquet representation.

    The hash is computed over the canonical Parquet serialization of the
    sorted-column table (``statistics=False``, ``compression="zstd"``) so it
    is a pure function of the persisted artifact: the same bytes a consumer
    reads back from the artifact store produce the same hash, and identical
    logical content always hashes identically regardless of in-memory column
    ordering.

    Version history:
      v1: pyarrow.ipc.new_file + writer.write_table (segfaults on some
          pyarrow/Python version combinations).
      v2: polars.DataFrame.write_ipc — deterministic, but IPC serialization
          of string columns is not stable across a Parquet round-trip, so
          the hash could not be recomputed from persisted artifacts.
      v3: polars.DataFrame.write_parquet (sorted columns, statistics=False,
          compression=zstd) — byte-stable across store/read-back, making the
          logical hash independently recomputable from canonical content.
    """
    import io

    sorted_cols = sorted(table.columns)
    table = table.select(sorted_cols)
    buf = io.BytesIO()
    table.write_parquet(buf, statistics=False, compression="zstd")
    return f"{TABLE_LOGICAL_HASH_VERSION}:{hashlib.sha256(buf.getvalue()).hexdigest()}"


def params_hash(params: JsonDict) -> str:
    """Shortcut for hashing a parameter dict."""
    return json_logical_hash(params)


# Metadata keys that record run provenance rather than artifact semantics.
# These must not participate in descriptor identity: the same deterministic
# artifact produced by a different run carries a different creating_run_id /
# source_artifact_id but is the same semantic artifact.
PROVENANCE_METADATA_KEYS = frozenset({
    "creating_run_id",
    "creating_run_step_id",
    "source_artifact_id",
})


def identity_metadata(metadata: JsonDict) -> JsonDict:
    """Return the identity-bearing subset of artifact metadata.

    Run-provenance keys are excluded; everything else (e.g. ``exclude_key``,
    ``purpose``, estimator format) is semantic and must distinguish otherwise
    byte-identical descriptors.
    """
    return {k: v for k, v in metadata.items() if k not in PROVENANCE_METADATA_KEYS}


def descriptor_id(
    *,
    artifact_type: str,
    role: str,
    media_type: str,
    kind: str,
    schema_version: str,
    logical_hash: str,
    physical_hash: str,
    metadata: JsonDict | None = None,
) -> str:
    """Deterministic descriptor ID encoding the complete semantic identity.

    Two descriptors collide (and are deduplicated as the *same* artifact) only
    when every identity-bearing field agrees: type, role, media type, evidence
    kind, versioned schema, logical hash, physical hash, and the hashed
    identity-bearing metadata subset. Identical bytes with a different
    schema/kind/media or different semantic metadata (e.g. ``exclude_key``)
    therefore produce distinct descriptors instead of silently adopting the
    first descriptor's semantics. Run-provenance metadata keys are excluded.
    """
    identity_md = identity_metadata(metadata or {})
    metadata_hash = json_logical_hash(identity_md) if identity_md else ""
    return "|".join([
        artifact_type,
        role,
        media_type,
        kind,
        schema_version,
        logical_hash,
        physical_hash,
        metadata_hash,
    ])


@dataclass(frozen=True)
class ArtifactRef:
    """Immutable reference to a stored artifact."""
    artifact_id: str
    artifact_type: str
    role: str
    path: str
    physical_hash: str
    logical_hash: str
    media_type: str = "application/octet-stream"
    created_at: str = ""
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "role": self.role,
            "path": self.path,
            "physical_hash": self.physical_hash,
            "logical_hash": self.logical_hash,
            "media_type": self.media_type,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


__all__ = [
    "CHUNK_SIZE",
    "PROVENANCE_METADATA_KEYS",
    "TABLE_LOGICAL_HASH_VERSION",
    "ArtifactRef",
    "descriptor_id",
    "identity_metadata",
    "json_logical_hash",
    "params_hash",
    "physical_hash",
    "relative_path",
    "table_logical_hash",
]
