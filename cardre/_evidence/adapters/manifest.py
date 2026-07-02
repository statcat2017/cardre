"""Manifest evidence adapters."""

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.store import ProjectStore


class ReportBundleAdapter:
    kind: EvidenceKind = EvidenceKind.REPORT_BUNDLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REPORT_BUNDLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class RunManifestAdapter:
    kind: EvidenceKind = EvidenceKind.RUN_MANIFEST
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.RUN_MANIFEST]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class TechnicalManifestIndexAdapter:
    kind: EvidenceKind = EvidenceKind.TECHNICAL_MANIFEST_INDEX
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.TECHNICAL_MANIFEST_INDEX]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ComparisonArtifactAdapter:
    kind: EvidenceKind = EvidenceKind.COMPARISON_ARTIFACT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.COMPARISON_ARTIFACT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}
