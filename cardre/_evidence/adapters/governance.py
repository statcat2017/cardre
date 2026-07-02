"""Governance evidence adapters."""

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
from cardre._evidence.models.governance import (
    ExplainabilityReport,
    FairnessReport,
    FeatureSelectionEvidence,
    HyperparameterTuningEvidence,
    ProxyRiskReport,
    RejectInferenceResult,
    RejectPopulationConfig,
    ResamplingEvidence,
    VariableClusteringEvidence,
)
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


class VariableClusteringAdapter:
    kind: EvidenceKind = EvidenceKind.VARIABLE_CLUSTERING
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.VARIABLE_CLUSTERING]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return VariableClusteringEvidence.from_json(data, artifact_id=art.artifact_id)


class FeatureSelectionEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.FEATURE_SELECTION_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FEATURE_SELECTION_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return FeatureSelectionEvidence.from_json(data, artifact_id=art.artifact_id)


class ResamplingEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.RESAMPLING_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.RESAMPLING_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ResamplingEvidence.from_json(data, artifact_id=art.artifact_id)


class HyperparameterTuningEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return HyperparameterTuningEvidence.from_json(data, artifact_id=art.artifact_id)


class ExplainabilityReportAdapter:
    kind: EvidenceKind = EvidenceKind.EXPLAINABILITY_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.EXPLAINABILITY_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ExplainabilityReport.from_json(data, artifact_id=art.artifact_id)


class FairnessReportAdapter:
    kind: EvidenceKind = EvidenceKind.FAIRNESS_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FAIRNESS_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return FairnessReport.from_json(data, artifact_id=art.artifact_id)


class ProxyRiskReportAdapter:
    kind: EvidenceKind = EvidenceKind.PROXY_RISK_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.PROXY_RISK_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ProxyRiskReport.from_json(data, artifact_id=art.artifact_id)


class RejectInferenceResultAdapter:
    kind: EvidenceKind = EvidenceKind.REJECT_INFERENCE_RESULT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REJECT_INFERENCE_RESULT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return RejectInferenceResult.from_json(data)


class RejectPopulationConfigAdapter:
    kind: EvidenceKind = EvidenceKind.REJECT_POPULATION_CONFIG
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REJECT_POPULATION_CONFIG]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return RejectPopulationConfig.from_json(data)
