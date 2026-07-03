"""Manifest evidence adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre._evidence.adapters._base import (
    candidate_passes_payload_check,
    match_by_role_type_media,
    match_by_schema_version,
    read_json_payload,
)
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.models.manifest import (
    ComparisonArtifact,
    ReportBundleEvidence,
    RunManifestEvidence,
    TechnicalManifestIndex,
)
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre.domain.artifacts import ArtifactRef
from cardre.store import ProjectStore


def _match(artifacts: list[ArtifactRef], profile: _Profile, store: ProjectStore) -> list[ArtifactRef]:
    schema_matches = match_by_schema_version(artifacts, profile)
    if schema_matches:
        return schema_matches
    candidates = match_by_role_type_media(artifacts, profile)
    if len(candidates) == 1:
        if candidate_passes_payload_check(candidates[0], profile, store):
            return candidates
        candidates = []
    return candidates


class ReportBundleAdapter:
    kind: EvidenceKind = EvidenceKind.REPORT_BUNDLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REPORT_BUNDLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ReportBundleEvidence.from_json(data, artifact_id=art.artifact_id)


class RunManifestAdapter:
    kind: EvidenceKind = EvidenceKind.RUN_MANIFEST
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.RUN_MANIFEST]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return RunManifestEvidence.from_json(data, artifact_id=art.artifact_id)


class TechnicalManifestIndexAdapter:
    kind: EvidenceKind = EvidenceKind.TECHNICAL_MANIFEST_INDEX
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.TECHNICAL_MANIFEST_INDEX]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return TechnicalManifestIndex.from_json(data, artifact_id=art.artifact_id)


class ComparisonArtifactAdapter:
    kind: EvidenceKind = EvidenceKind.COMPARISON_ARTIFACT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.COMPARISON_ARTIFACT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ComparisonArtifact.from_json(data, artifact_id=art.artifact_id)
