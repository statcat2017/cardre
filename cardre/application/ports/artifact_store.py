"""Ports for staged artifact writing and reading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from cardre.domain.diagnostics import JsonDict


@dataclass(frozen=True)
class StagedArtifact:
    staging_path: Path
    provisional_artifact_id: str
    physical_hash: str
    logical_hash: str
    media_type: str
    schema_version: str
    role: str
    artifact_type: str
    metadata: JsonDict


@runtime_checkable
class StagedArtifactWriter(Protocol):
    def stage_json(self, role: str, kind: str, payload: JsonDict,
                   metadata: JsonDict | None = None) -> StagedArtifact: ...
    def stage_table(self, role: str, kind: str, frame: object,
                    metadata: JsonDict | None = None) -> StagedArtifact: ...
    def stage_bytes(self, role: str, kind: str, data: bytes,
                    media_type: str, logical_hash: str,
                    metadata: JsonDict | None = None) -> StagedArtifact: ...
    def publish(self, staged: StagedArtifact) -> Path: ...


@runtime_checkable
class ArtifactReader(Protocol):
    def read_bytes(self, artifact: object) -> bytes: ...
    def resolve_path(self, artifact: object) -> Path: ...
