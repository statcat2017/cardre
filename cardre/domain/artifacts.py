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


TABLE_LOGICAL_HASH_VERSION = "v2"


def table_logical_hash(table: Any) -> str:
    """SHA-256 of a sorted-column Arrow IPC representation.

    Version history:
      v1: pyarrow.ipc.new_file + writer.write_table (segfaults on some
          pyarrow/Python version combinations).
      v2: polars.DataFrame.write_ipc — avoids the buggy C++ path.
    """
    import io

    sorted_cols = sorted(table.columns)
    table = table.select(sorted_cols)
    buf = io.BytesIO()
    table.write_ipc(buf)
    return f"{TABLE_LOGICAL_HASH_VERSION}:{hashlib.sha256(buf.getvalue()).hexdigest()}"


def params_hash(params: JsonDict) -> str:
    """Shortcut for hashing a parameter dict."""
    return json_logical_hash(params)


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

    @classmethod
    def from_dict(cls, data: JsonDict) -> ArtifactRef:
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            role=data["role"],
            path=data["path"],
            physical_hash=data["physical_hash"],
            logical_hash=data["logical_hash"],
            media_type=data.get("media_type", "application/octet-stream"),
            created_at=data.get("created_at", ""),
            metadata=dict(data.get("metadata", {})),
        )


__all__ = [
    "CHUNK_SIZE",
    "TABLE_LOGICAL_HASH_VERSION",
    "ArtifactRef",
    "json_logical_hash",
    "params_hash",
    "physical_hash",
    "relative_path",
    "table_logical_hash",
]
