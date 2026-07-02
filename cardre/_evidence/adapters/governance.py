"""Governance evidence adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.adapters._base import (
    candidate_passes_payload_check,
    match_by_payload_key,
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


class VariableClusteringAdapter:
    kind: EvidenceKind = EvidenceKind.VARIABLE_CLUSTERING
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.VARIABLE_CLUSTERING]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"method", "clusters"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return VariableClusteringEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class FeatureSelectionEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.FEATURE_SELECTION_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FEATURE_SELECTION_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"selected", "rejected"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return FeatureSelectionEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class ResamplingEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.RESAMPLING_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.RESAMPLING_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"original", "resampled"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ResamplingEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class HyperparameterTuningEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"best_params", "best_score"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return HyperparameterTuningEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class ExplainabilityReportAdapter:
    kind: EvidenceKind = EvidenceKind.EXPLAINABILITY_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.EXPLAINABILITY_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"model_family", "limitations"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ExplainabilityReport.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class FairnessReportAdapter:
    kind: EvidenceKind = EvidenceKind.FAIRNESS_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.FAIRNESS_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"roles", "parity_summary"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return FairnessReport.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class ProxyRiskReportAdapter:
    kind: EvidenceKind = EvidenceKind.PROXY_RISK_REPORT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.PROXY_RISK_REPORT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"proxy_flags", "overall_risk"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ProxyRiskReport.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class RejectInferenceResultAdapter:
    kind: EvidenceKind = EvidenceKind.REJECT_INFERENCE_RESULT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REJECT_INFERENCE_RESULT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return RejectInferenceResult.from_json(data)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class RejectPopulationConfigAdapter:
    kind: EvidenceKind = EvidenceKind.REJECT_POPULATION_CONFIG
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REJECT_POPULATION_CONFIG]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return RejectPopulationConfig.from_json(data)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError
