"""Sample evidence adapters."""

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
from cardre._evidence.models.sample import (
    ExclusionSummary,
    ModellingMetadata,
    ProfileSummary,
    SampleDefinition,
    SplitSummary,
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


class ModellingMetadataAdapter:
    kind: EvidenceKind = EvidenceKind.MODELLING_METADATA
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.MODELLING_METADATA]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ModellingMetadata.from_json(data, artifact_id=art.artifact_id)


class SampleDefinitionAdapter:
    kind: EvidenceKind = EvidenceKind.SAMPLE_DEFINITION
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.SAMPLE_DEFINITION]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return SampleDefinition.from_json(data, artifact_id=art.artifact_id)


class SplitSummaryAdapter:
    kind: EvidenceKind = EvidenceKind.SPLIT_SUMMARY
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.SPLIT_SUMMARY]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return SplitSummary.from_json(data, artifact_id=art.artifact_id)


class ProfileSummaryAdapter:
    kind: EvidenceKind = EvidenceKind.PROFILE_SUMMARY
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.PROFILE_SUMMARY]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ProfileSummary.from_json(data, artifact_id=art.artifact_id)


class ExclusionSummaryAdapter:
    kind: EvidenceKind = EvidenceKind.EXCLUSION_SUMMARY
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.EXCLUSION_SUMMARY]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ExclusionSummary.from_json(data, artifact_id=art.artifact_id)
