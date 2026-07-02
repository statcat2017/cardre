"""WOE / score application evidence adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.adapters._base import (
    candidate_passes_payload_check,
    match_by_parquet_columns,
    match_by_payload_key,
    match_by_role_type_media,
    match_by_schema_version,
    read_json_payload,
)
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.models.apply import ApplyModelEvidence, ApplyWoeEvidence, ScoredDataset
from cardre._evidence.models.woe import IvTable, WoeIvEvidence, WoeTable, WoeTransformEvidence
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre.store import ProjectStore


class WoeTransformEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_TRANSFORM_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_TRANSFORM_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"target_column", "transformed_variables"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return WoeTransformEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class WoeTableAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_TABLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_TABLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_parquet_columns(
            artifacts, "report", "application/vnd.apache.parquet", {"variable", "bin_id", "woe"}, store,
        )
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        lf = pl.scan_parquet(path)
        cols = lf.collect_schema().names()
        df = lf.select(["variable", "bin_id", "woe"]).collect()
        mapping: dict[str, dict[str, float]] = {}
        for row in df.iter_rows():
            var = str(row[0])
            bid = str(row[1])
            wv = row[2]
            if wv is not None:
                mapping.setdefault(var, {})[bid] = float(wv)
        return WoeTable(mapping=mapping, columns=cols, dataframe=lf, source_artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class IvTableAdapter:
    kind: EvidenceKind = EvidenceKind.IV_TABLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.IV_TABLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        # IV_TABLE has empty schema_version; skip schema phase.
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_parquet_columns(
            artifacts, "report", "application/vnd.apache.parquet", {"iv", "variable"}, store,
        )
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        lf = pl.scan_parquet(path)
        return IvTable(dataframe=lf, columns=lf.collect_schema().names(), source_artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class WoeIvEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_IV_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_IV_EVIDENCE]

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
        return WoeIvEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class ApplyWoeEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.APPLY_WOE_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.APPLY_WOE_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"roles", "policy"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ApplyWoeEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class ApplyModelEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.APPLY_MODEL_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.APPLY_MODEL_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        schema_matches = match_by_schema_version(artifacts, self.profile)
        if schema_matches:
            return schema_matches
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        legacy = match_by_payload_key(artifacts, {"roles", "model_artifact_id"}, store)
        if legacy:
            return legacy
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ApplyModelEvidence.from_json(data, artifact_id=art.artifact_id)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError


class ScoredDatasetAdapter:
    kind: EvidenceKind = EvidenceKind.SCORED_DATASET
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.SCORED_DATASET]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        # SCORED_DATASET has empty schema_version; skip schema phase.
        candidates = match_by_role_type_media(artifacts, self.profile)
        if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], self.profile, store):
            return candidates
        return candidates

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        lf = pl.scan_parquet(path)
        return ScoredDataset(dataframe=lf)

    def summarise(self, artifact_row: dict, typed: Any) -> dict:
        raise NotImplementedError
