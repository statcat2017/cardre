"""Ports for staged artifact writing and reading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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
    def stage_table(self, role: str, kind: str, frame: Any,
                    metadata: JsonDict | None = None,
                    artifact_type: str | None = None) -> StagedArtifact: ...
    def stage_bytes(self, role: str, kind: str, data: bytes,
                    media_type: str, logical_hash: str,
                    metadata: JsonDict | None = None) -> StagedArtifact: ...
    def publish(self, staged: StagedArtifact) -> Path: ...


@runtime_checkable
class DurableArtifactWriter(StagedArtifactWriter, Protocol):
    """Staged writer plus the durable-publication operations.

    The durable publication protocol (R2) keeps files in staging until the DB
    transaction commits, then finalizes them: ``dest_path`` computes the
    content-addressed object path without moving the file, and ``finalize``
    moves it after commit. Use cases that publish via the outbox must depend
    on this port, not on concrete filesystem methods.
    """

    def dest_path(self, staged: StagedArtifact) -> Path: ...
    def finalize(self, staged: StagedArtifact) -> Path: ...


@runtime_checkable
class ArtifactReader(Protocol):
    @property
    def root(self) -> Path: ...
    def read_bytes(self, artifact: object) -> bytes: ...
    def resolve_path(self, artifact: object) -> Path: ...
