"""Filesystem-backed artifact store with staging and atomic publish."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import polars as pl

from cardre.application.ports.artifact_store import StagedArtifact
from cardre.domain.artifacts import json_logical_hash, physical_hash, table_logical_hash


class FsArtifactStore:
    """Content-addressed artifact store.

    Artifacts are staged to ``<root>/.staging/{uuid}`` and atomically
    published to ``<root>/objects/{physical_hash[:2]}/{physical_hash}``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._staging_dir = root / ".staging"

    def _stage(self, data: bytes, logical_hash: str, media_type: str,
               schema_version: str, role: str, artifact_type: str,
               metadata: dict | None) -> StagedArtifact:
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        staging = self._staging_dir / uuid.uuid4().hex
        staging.write_bytes(data)
        phys = physical_hash(staging)
        return StagedArtifact(
            staging_path=staging,
            provisional_artifact_id=str(uuid.uuid4()),
            physical_hash=phys,
            logical_hash=logical_hash,
            media_type=media_type,
            schema_version=schema_version,
            role=role,
            artifact_type=artifact_type,
            metadata=metadata or {},
        )

    def stage_json(self, role: str, kind: str, payload: dict,
                   metadata: dict | None = None) -> StagedArtifact:
        logical = json_logical_hash(payload)
        data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return self._stage(data, logical, "application/json", kind, role, kind.split(".")[-1] if "." in kind else kind, metadata)

    def stage_table(self, role: str, kind: str, frame: pl.DataFrame,
                    metadata: dict | None = None) -> StagedArtifact:
        logical = table_logical_hash(frame)
        import io
        buf = io.BytesIO()
        frame.write_parquet(buf, statistics=False, compression="zstd")
        return self._stage(buf.getvalue(), logical, "application/vnd.apache.parquet",
                           kind, role, kind.split(".")[-1] if "." in kind else kind, metadata)

    def stage_bytes(self, role: str, kind: str, data: bytes,
                    media_type: str, logical_hash: str,
                    metadata: dict | None = None) -> StagedArtifact:
        return self._stage(data, logical_hash, media_type, kind, role,
                           kind.split(".")[-1] if "." in kind else kind, metadata)

    def publish(self, staged: StagedArtifact) -> Path:
        dest = self._root / "objects" / staged.physical_hash[:2] / staged.physical_hash
        dest.parent.mkdir(parents=True, exist_ok=True)
        staged.staging_path.replace(dest)
        return dest

    def read_bytes(self, artifact: object) -> bytes:
        if isinstance(artifact, dict):
            storage_key = artifact.get("storage_key", artifact.get("physical_hash", ""))
        elif hasattr(artifact, "storage_key"):
            storage_key = artifact.storage_key
        elif hasattr(artifact, "physical_hash"):
            storage_key = artifact.physical_hash
        else:
            storage_key = str(artifact)
        path = self._root / "objects" / storage_key[:2] / storage_key
        return path.read_bytes()

    def resolve_path(self, artifact: object) -> Path:
        if isinstance(artifact, dict):
            storage_key = artifact.get("storage_key", artifact.get("physical_hash", ""))
        elif hasattr(artifact, "storage_key"):
            storage_key = artifact.storage_key
        elif hasattr(artifact, "physical_hash"):
            storage_key = artifact.physical_hash
        else:
            storage_key = str(artifact)
        return self._root / "objects" / storage_key[:2] / storage_key

    def gc_staging(self) -> None:
        import shutil
        if self._staging_dir.is_dir():
            shutil.rmtree(self._staging_dir)
