"""Governance evidence adapters."""

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.store import ProjectStore


class VariableClusteringAdapter:
    kind: EvidenceKind = EvidenceKind.VARIABLE_CLUSTERING
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.VARIABLE_CLUSTERING]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class FeatureSelectionEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.FEATURE_SELECTION_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FEATURE_SELECTION_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ResamplingEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.RESAMPLING_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.RESAMPLING_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class HyperparameterTuningEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ExplainabilityReportAdapter:
    kind: EvidenceKind = EvidenceKind.EXPLAINABILITY_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.EXPLAINABILITY_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class FairnessReportAdapter:
    kind: EvidenceKind = EvidenceKind.FAIRNESS_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FAIRNESS_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class ProxyRiskReportAdapter:
    kind: EvidenceKind = EvidenceKind.PROXY_RISK_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.PROXY_RISK_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class RejectInferenceResultAdapter:
    kind: EvidenceKind = EvidenceKind.REJECT_INFERENCE_RESULT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REJECT_INFERENCE_RESULT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}


class RejectPopulationConfigAdapter:
    kind: EvidenceKind = EvidenceKind.REJECT_POPULATION_CONFIG
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REJECT_POPULATION_CONFIG]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return ArtifactEvidenceReader(store)._match(artifacts, self.kind)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        return ArtifactEvidenceReader(store)._parse(art, self.kind)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        return {}
