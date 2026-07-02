"""Model evidence adapters."""

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.store import ProjectStore


class ModelArtifactAdapter:
    kind: EvidenceKind = EvidenceKind.MODEL_ARTIFACT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.MODEL_ARTIFACT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class EnsembleModelArtifactAdapter:
    kind: EvidenceKind = EvidenceKind.ENSEMBLE_MODEL_ARTIFACT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.ENSEMBLE_MODEL_ARTIFACT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ScoreScalingAdapter:
    kind: EvidenceKind = EvidenceKind.SCORE_SCALING
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.SCORE_SCALING]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class FrozenScorecardBundleAdapter:
    kind: EvidenceKind = EvidenceKind.FROZEN_SCORECARD_BUNDLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FROZEN_SCORECARD_BUNDLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}
