from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import polars as pl

from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.artifacts import (
    descriptor_id,
    json_logical_hash,
    physical_hash,
    table_logical_hash,
)


class FsArtifactStore:
    """Content-addressed artifact store.

    Artifacts are staged to ``<root>/.staging/{uuid}`` and atomically
    published to ``<root>/objects/{physical_hash[:2]}/{physical_hash}``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._staging_dir = root / ".staging"

    @property
    def root(self) -> Path:
        return self._root

    def _stage(self, data: bytes, logical_hash: str, media_type: str,
               schema_version: str, role: str, artifact_type: str,
               metadata: dict[str, Any] | None) -> StagedArtifact:
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        staging = self._staging_dir / uuid.uuid4().hex
        staging.write_bytes(data)
        phys = physical_hash(staging)
        # Deterministic descriptor ID encoding the complete semantic identity.
        # Identical bytes with a different kind/media/schema/logical hash map to
        # a distinct descriptor, so no second descriptor silently adopts the
        # first's semantics. Run-provenance metadata (creating_run_id, source
        # ids) is deliberately excluded from identity.
        meta = metadata or {}
        versioned_schema = str(meta.get("schema_version", ""))
        provisional_artifact_id = descriptor_id(
            artifact_type=artifact_type,
            role=role,
            media_type=media_type,
            kind=schema_version,
            schema_version=versioned_schema,
            logical_hash=logical_hash,
            physical_hash=phys,
            metadata=meta,
        )
        return StagedArtifact(
            staging_path=staging,
            provisional_artifact_id=provisional_artifact_id,
            physical_hash=phys,
            logical_hash=logical_hash,
            media_type=media_type,
            schema_version=schema_version,
            role=role,
            artifact_type=artifact_type,
            metadata=meta,
        )

    def stage_json(self, role: str, kind: str, payload: dict[str, Any],
                   metadata: dict[str, Any] | None = None) -> StagedArtifact:
        logical = json_logical_hash(payload)
        data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return self._stage(data, logical, "application/json", kind, role, kind.split(".")[-1] if "." in kind else kind, metadata)

    def stage_table(self, role: str, kind: str, frame: pl.DataFrame,
                    metadata: dict[str, Any] | None = None,
                    artifact_type: str | None = None) -> StagedArtifact:
        logical = table_logical_hash(frame)
        import io
        buf = io.BytesIO()
        frame.write_parquet(buf, statistics=False, compression="zstd")
        staged_type = artifact_type or (kind.split(".")[-1] if "." in kind else kind)
        return self._stage(buf.getvalue(), logical, "application/vnd.apache.parquet",
                           kind, role, staged_type, metadata)

    def stage_bytes(self, role: str, kind: str, data: bytes,
                    media_type: str, logical_hash: str,
                    metadata: dict[str, Any] | None = None) -> StagedArtifact:
        return self._stage(data, logical_hash, media_type, kind, role,
                           kind.split(".")[-1] if "." in kind else kind, metadata)

    def publish(self, staged: StagedArtifact) -> Path:
        """Publish a staged artifact to its content-addressed object path.

        Moves the file out of staging immediately. Callers that need the
        durable publication protocol (DB commit before the file leaves
        staging) should use :meth:`dest_path` + :meth:`finalize` instead.
        """
        dest = self.dest_path(staged)
        dest.parent.mkdir(parents=True, exist_ok=True)
        staged.staging_path.replace(dest)
        return dest

    def dest_path(self, staged: StagedArtifact) -> Path:
        """Compute the content-addressed object path without moving the file."""
        return self._root / "objects" / staged.physical_hash[:2] / staged.physical_hash

    def object_path(self, physical_hash: str) -> Path:
        """Compute the object path for a physical hash (idempotent with publish)."""
        return self._root / "objects" / physical_hash[:2] / physical_hash

    def finalize(self, staged: StagedArtifact) -> Path:
        """Move a staged file to its object path after the DB mutation is durable.

        Idempotent: if the object already exists (duplicate bytes), the
        staging file is discarded and the existing object is kept.
        """
        dest = self.dest_path(staged)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            staged.staging_path.replace(dest)
        elif staged.staging_path.exists():
            staged.staging_path.unlink()
        return dest

    def finalize_staged_file(self, staging_source: str, physical_hash: str) -> Path:
        """Finalize a staged file described by an outbox row (reconciliation).

        Idempotent with :meth:`finalize`: moves the staging file to its
        content-addressed object path, or verifies the object already exists.
        """
        dest = self.object_path(physical_hash)
        if dest.exists():
            if staging_source and Path(staging_source).exists():
                Path(staging_source).unlink()
            return dest
        if not staging_source:
            raise FileNotFoundError(f"object {dest} missing and no staging source recorded")
        source = Path(staging_source)
        if not source.exists():
            raise FileNotFoundError(f"staged file {staging_source} missing; cannot finalize object {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.replace(dest)
        return dest

    def read_bytes(self, artifact: object) -> bytes:
        key = self._storage_key(artifact)
        return (self._root / "objects" / key[:2] / key).read_bytes()

    def resolve_path(self, artifact: object) -> Path:
        key = self._storage_key(artifact)
        return self._root / "objects" / key[:2] / key

    @staticmethod
    def _storage_key(artifact: object) -> str:
        if isinstance(artifact, dict):
            return str(artifact.get("storage_key") or artifact.get("physical_hash") or "")
        if hasattr(artifact, "storage_key"):
            return str(artifact.storage_key)
        if hasattr(artifact, "physical_hash"):
            return str(artifact.physical_hash)
        return str(artifact)

    def gc_staging(self) -> None:
        import shutil
        if self._staging_dir.is_dir():
            shutil.rmtree(self._staging_dir)
