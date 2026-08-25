"""Reusable minimal fakes for port contract tests (Batch 2A).

Each fake is a faithful, *minimal* implementation of its port that mirrors the
real adapter's observable contract (transaction lifecycle, content-addressed
identity, persistence) without bypassing the behaviour under test. They carry
no external I/O.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.artifacts import descriptor_id, json_logical_hash, table_logical_hash


class DeterministicClock:
    """ClockPort implementation returning a sequence of nondecreasing UTC ISO strings."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    def now_iso(self) -> str:
        value = self._now.isoformat()
        self._now += timedelta(seconds=1)
        return value


class DeterministicIdGenerator:
    """IdGeneratorPort implementation producing a deterministic, unique sequence."""

    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n:04d}"


class MemoryProjectRegistry:
    """In-memory ProjectRegistryPort — persists id->root mappings in a dict."""

    def __init__(self) -> None:
        self._mapping: dict[str, str] = {}

    def register(self, project_id: str, root: str | Path) -> None:
        self._mapping[project_id] = str(Path(root).resolve())

    def resolve_root(self, project_id: str) -> Path | None:
        root = self._mapping.get(project_id)
        if root is None:
            return None
        return Path(root).resolve()

    def list_all(self) -> dict[str, str]:
        return dict(self._mapping)


class MemoryArtifactStore:
    """In-memory implementation of the staged/durable/read artifact ports.

    Content-addressed by physical hash. Bytes "live" in staging until
    ``publish()``/``finalize()`` moves them into the object namespace, mirroring
    ``FsArtifactStore``. Supports json, table and bytes staging.
    """

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._staging: dict[str, bytes] = {}
        self._seq = 0

    @property
    def root(self) -> Path:
        return Path("/mem/artifact-store")

    def _stage(self, data: bytes, logical_hash: str, media_type: str,
               schema_version: str, role: str, artifact_type: str,
               metadata: dict[str, object] | None) -> StagedArtifact:
        self._seq += 1
        physical = hashlib.sha256(data).hexdigest()
        staging_path = Path(".staging") / f"mem-{self._seq}"
        self._staging[str(staging_path)] = data
        meta = metadata or {}
        provisional = descriptor_id(
            artifact_type=artifact_type,
            role=role,
            media_type=media_type,
            kind=schema_version,
            schema_version=str(meta.get("schema_version", "")),
            logical_hash=logical_hash,
            physical_hash=physical,
            metadata=meta,
        )
        return StagedArtifact(
            staging_path=staging_path,
            provisional_artifact_id=provisional,
            physical_hash=physical,
            logical_hash=logical_hash,
            media_type=media_type,
            schema_version=schema_version,
            role=role,
            artifact_type=artifact_type,
            metadata=meta,
        )

    def stage_json(self, role: str, kind: str, payload: dict[str, object],
                   metadata: dict[str, object] | None = None) -> StagedArtifact:
        logical = json_logical_hash(payload)
        data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        artifact_type = kind.split(".")[-1] if "." in kind else kind
        return self._stage(data, logical, "application/json", kind, role, artifact_type, metadata)

    def stage_table(self, role: str, kind: str, frame, metadata: dict[str, object] | None = None,
                    artifact_type: str | None = None) -> StagedArtifact:
        logical = table_logical_hash(frame)
        buf = io.BytesIO()
        frame.write_parquet(buf, statistics=False, compression="zstd")
        staged_type = artifact_type or (kind.split(".")[-1] if "." in kind else kind)
        return self._stage(buf.getvalue(), logical, "application/vnd.apache.parquet",
                           kind, role, staged_type, metadata)

    def stage_bytes(self, role: str, kind: str, data: bytes, media_type: str,
                    logical_hash: str, metadata: dict[str, object] | None = None) -> StagedArtifact:
        artifact_type = kind.split(".")[-1] if "." in kind else kind
        return self._stage(data, logical_hash, media_type, kind, role, artifact_type, metadata)

    def dest_path(self, staged: StagedArtifact) -> Path:
        return self.object_path(staged.physical_hash)

    def object_path(self, physical_hash: str) -> Path:
        return self.root / "objects" / physical_hash[:2] / physical_hash

    def publish(self, staged: StagedArtifact) -> Path:
        dest = self.dest_path(staged)
        key = str(staged.staging_path)
        if key not in self._staging:
            raise FileNotFoundError(f"staged file {key} missing; cannot publish object {dest}")
        self._objects[staged.physical_hash] = self._staging.pop(key)
        return dest

    def finalize(self, staged: StagedArtifact) -> Path:
        dest = self.dest_path(staged)
        key = str(staged.staging_path)
        if staged.physical_hash not in self._objects:
            if key not in self._staging:
                raise FileNotFoundError(f"staged file {key} missing; cannot finalize object {dest}")
            self._objects[staged.physical_hash] = self._staging.pop(key)
        elif key in self._staging:
            self._staging.pop(key)
        return dest

    def read_bytes(self, artifact: object) -> bytes:
        key = self._storage_key(artifact)
        try:
            return self._objects[key]
        except KeyError:
            raise FileNotFoundError(
                f"object {self.object_path(key)} missing; cannot read bytes"
            ) from None

    def resolve_path(self, artifact: object) -> Path:
        # Faithful to ``FsArtifactStore.resolve_path``: returns the
        # content-addressed object path without checking existence, so a
        # missing object still yields a path (only ``read_bytes`` raises).
        return self.object_path(self._storage_key(artifact))

    @staticmethod
    def _storage_key(artifact: object) -> str:
        # Priority mirrors ``FsArtifactStore._storage_key``: storage_key wins
        # over physical_hash, and attributes before the raw fallback.
        if isinstance(artifact, dict):
            return str(artifact.get("storage_key") or artifact.get("physical_hash") or "")
        if hasattr(artifact, "storage_key"):
            return str(artifact.storage_key)
        if hasattr(artifact, "physical_hash"):
            return str(artifact.physical_hash)
        return str(artifact)
