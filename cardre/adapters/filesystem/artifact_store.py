from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

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
               metadata: dict[str, Any] | None) -> StagedArtifact:
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

    def stage_json(self, role: str, kind: str, payload: dict[str, Any],
                   metadata: dict[str, Any] | None = None) -> StagedArtifact:
        logical = json_logical_hash(payload)
        data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return self._stage(data, logical, "application/json", kind, role, kind.split(".")[-1] if "." in kind else kind, metadata)

    def stage_table(self, role: str, kind: str, frame: pl.DataFrame,
                    metadata: dict[str, Any] | None = None) -> StagedArtifact:
        logical = table_logical_hash(frame)
        import io
        buf = io.BytesIO()
        frame.write_parquet(buf, statistics=False, compression="zstd")
        return self._stage(buf.getvalue(), logical, "application/vnd.apache.parquet",
                           kind, role, kind.split(".")[-1] if "." in kind else kind, metadata)

    def stage_bytes(self, role: str, kind: str, data: bytes,
                    media_type: str, logical_hash: str,
                    metadata: dict[str, Any] | None = None) -> StagedArtifact:
        return self._stage(data, logical_hash, media_type, kind, role,
                           kind.split(".")[-1] if "." in kind else kind, metadata)

    def publish(self, staged: StagedArtifact) -> Path:
        dest = self._root / "objects" / staged.physical_hash[:2] / staged.physical_hash
        dest.parent.mkdir(parents=True, exist_ok=True)
        staged.staging_path.replace(dest)
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
