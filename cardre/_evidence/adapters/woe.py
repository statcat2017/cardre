"""WOE / score application evidence adapters."""

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.store import ProjectStore


class WoeTransformEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_TRANSFORM_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_TRANSFORM_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class WoeTableAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_TABLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_TABLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class IvTableAdapter:
    kind: EvidenceKind = EvidenceKind.IV_TABLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.IV_TABLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class WoeIvEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_IV_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_IV_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ApplyWoeEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.APPLY_WOE_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.APPLY_WOE_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ApplyModelEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.APPLY_MODEL_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.APPLY_MODEL_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ScoredDatasetAdapter:
    kind: EvidenceKind = EvidenceKind.SCORED_DATASET
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.SCORED_DATASET]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}
