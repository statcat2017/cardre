"""Model evidence adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.adapters._base import (
    candidate_passes_payload_check,
    match_by_role_type_media,
    match_by_schema_version,
    read_json_payload,
)
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.models.model import ModelArtifact, ScoreScaling
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
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


class ModelArtifactAdapter:
    kind: EvidenceKind = EvidenceKind.MODEL_ARTIFACT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.MODEL_ARTIFACT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ModelArtifact.from_json(data, artifact_id=art.artifact_id)


class EnsembleModelArtifactAdapter:
    kind: EvidenceKind = EvidenceKind.ENSEMBLE_MODEL_ARTIFACT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.ENSEMBLE_MODEL_ARTIFACT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ModelArtifact.from_json(data, artifact_id=art.artifact_id)


class ScoreScalingAdapter:
    kind: EvidenceKind = EvidenceKind.SCORE_SCALING
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.SCORE_SCALING]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ScoreScaling.from_json(data, artifact_id=art.artifact_id)


class FrozenScorecardBundleAdapter:
    kind: EvidenceKind = EvidenceKind.FROZEN_SCORECARD_BUNDLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FROZEN_SCORECARD_BUNDLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return data
