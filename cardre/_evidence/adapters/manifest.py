"""Manifest evidence adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.adapters._base import (
    candidate_passes_payload_check,
    match_by_artifact_type,
    match_by_payload_key,
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
from cardre.store import ProjectStore


class ReportBundleAdapter:
    kind: EvidenceKind = EvidenceKind.REPORT_BUNDLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.REPORT_BUNDLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"project_id", "run_id", "summary", "source"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ReportBundleEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class RunManifestAdapter:
    kind: EvidenceKind = EvidenceKind.RUN_MANIFEST
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.RUN_MANIFEST]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_artifact_type(
            artifacts, "run_manifest", store, {"manifest_version", "run_id", "steps"},
        )
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return RunManifestEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class TechnicalManifestIndexAdapter:
    kind: EvidenceKind = EvidenceKind.TECHNICAL_MANIFEST_INDEX
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.TECHNICAL_MANIFEST_INDEX]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"manifests"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return TechnicalManifestIndex.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class ComparisonArtifactAdapter:
    kind: EvidenceKind = EvidenceKind.COMPARISON_ARTIFACT
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.COMPARISON_ARTIFACT]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_artifact_type(
            artifacts, "branch_comparison", store,
            {"comparison_type", "baseline_branch_id", "challenger_branch_id"},
        )
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ComparisonArtifact.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError
