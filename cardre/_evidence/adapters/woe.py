"""WOE / score application evidence adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.adapters._base import (
    candidate_passes_payload_check,
    match_by_role_type_media,
    match_by_schema_version,
    read_json_payload,
)
from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.models.apply import ApplyModelEvidence, ApplyWoeEvidence, ScoredDataset
from cardre._evidence.models.woe import IvTable, WoeIvEvidence, WoeTable, WoeTransformEvidence
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre.store import ProjectStore


def _match(artifacts: list[ArtifactRef], profile: _Profile, store: ProjectStore) -> list[ArtifactRef]:
    schema_matches = match_by_schema_version(artifacts, profile)
    if schema_matches:
        return schema_matches
    candidates = match_by_role_type_media(artifacts, profile)
    if len(candidates) == 1 and candidate_passes_payload_check(candidates[0], profile, store):
        return candidates
    return candidates


class WoeTransformEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_TRANSFORM_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_TRANSFORM_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return WoeTransformEvidence.from_json(data, artifact_id=art.artifact_id)


class WoeTableAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_TABLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_TABLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

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


class IvTableAdapter:
    kind: EvidenceKind = EvidenceKind.IV_TABLE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.IV_TABLE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        lf = pl.scan_parquet(path)
        return IvTable(dataframe=lf, columns=lf.collect_schema().names(), source_artifact_id=art.artifact_id)


class WoeIvEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.WOE_IV_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.WOE_IV_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return WoeIvEvidence.from_json(data, artifact_id=art.artifact_id)


class ApplyWoeEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.APPLY_WOE_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.APPLY_WOE_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ApplyWoeEvidence.from_json(data, artifact_id=art.artifact_id)


class ApplyModelEvidenceAdapter:
    kind: EvidenceKind = EvidenceKind.APPLY_MODEL_EVIDENCE
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.APPLY_MODEL_EVIDENCE]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        data = read_json_payload(path)
        return ApplyModelEvidence.from_json(data, artifact_id=art.artifact_id)


class ScoredDatasetAdapter:
    kind: EvidenceKind = EvidenceKind.SCORED_DATASET
    profile: _Profile = EVIDENCE_PROFILES[EvidenceKind.SCORED_DATASET]

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]:
        return _match(artifacts, self.profile, store)

    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any:
        lf = pl.scan_parquet(path)
        return ScoredDataset(dataframe=lf)
