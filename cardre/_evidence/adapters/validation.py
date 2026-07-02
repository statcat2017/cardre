"""Validation evidence adapters."""

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.store import ProjectStore


class ValidationMetricsAdapter:
    kind: EvidenceKind = EvidenceKind.VALIDATION_METRICS
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.VALIDATION_METRICS]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ValidationEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.VALIDATION_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.VALIDATION_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class CutoffAnalysisAdapter:
    kind: EvidenceKind = EvidenceKind.CUTOFF_ANALYSIS
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.CUTOFF_ANALYSIS]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class CalibrationReportAdapter:
    kind: EvidenceKind = EvidenceKind.CALIBRATION_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.CALIBRATION_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}
