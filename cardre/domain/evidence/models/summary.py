"""Evidence summary data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactEvidenceSummary:
    artifact_id: str
    role: str
    artifact_type: str
    media_type: str
    schema_version: str = ""
    kind: str = ""
    source_artifact_id: str = ""
