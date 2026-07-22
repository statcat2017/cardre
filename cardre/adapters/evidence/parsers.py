"""Evidence adapter registry, factory, and matching helpers.

Combines the adapter table and matching logic previously split across
``cardre/_evidence/adapters/__init__.py`` and ``_base.py``.  Uses
``ArtifactReader`` instead of ``ProjectStore``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from cardre._evidence.kinds import EvidenceKind, EvidenceParseError
from cardre._evidence.models.apply import ApplyModelEvidence, ApplyWoeEvidence, ScoredDataset
from cardre._evidence.models.binning import (
    BinDefinition,
    ManualBinningOverrides,
    SelectionDefinition,
)
from cardre._evidence.models.diagnostics import (
    CalibrationDiagnostics,
    CoefficientSignDiagnostics,
    SeparationDiagnostics,
    VifDiagnostics,
)
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
from cardre._evidence.models.manifest import (
    ComparisonArtifact,
    ReportBundleEvidence,
    TechnicalManifestIndex,
)
from cardre._evidence.models.model import ScoreScaling
from cardre._evidence.models.sample import (
    ExclusionSummary,
    ModellingMetadata,
    ProfileSummary,
    SampleDefinition,
    SplitSummary,
)
from cardre._evidence.models.validation import CutoffAnalysis, ValidationMetrics
from cardre._evidence.models.woe import IvTable, WoeIvEvidence, WoeTable, WoeTransformEvidence
from cardre._evidence.profiles import EVIDENCE_PROFILES, _Profile
from cardre.application.ports.artifact_store import ArtifactReader
from cardre.domain.artifacts import ArtifactRef
from cardre.modeling.schema import ModelArtifactV1


@dataclass(frozen=True)
class AdapterSpec:
    profile: _Profile
    parse: Callable[[Path, ArtifactRef, ArtifactReader], Any]


EVIDENCE_ADAPTERS: dict[EvidenceKind, AdapterSpec] = {
    EvidenceKind.BIN_DEFINITION: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.BIN_DEFINITION],
        parse=lambda path, art, reader: BinDefinition.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.CALIBRATION_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.CALIBRATION_REPORT],
        parse=lambda path, art, reader: read_json_payload(path),
    ),
    EvidenceKind.COMPARISON_ARTIFACT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.COMPARISON_ARTIFACT],
        parse=lambda path, art, reader: ComparisonArtifact.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.CUTOFF_ANALYSIS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.CUTOFF_ANALYSIS],
        parse=lambda path, art, reader: CutoffAnalysis.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.ENSEMBLE_MODEL_ARTIFACT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.ENSEMBLE_MODEL_ARTIFACT],
        parse=lambda path, art, reader: ModelArtifactV1.from_dict(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.EXCLUSION_SUMMARY: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.EXCLUSION_SUMMARY],
        parse=lambda path, art, reader: ExclusionSummary.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.EXPLAINABILITY_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.EXPLAINABILITY_REPORT],
        parse=lambda path, art, reader: ExplainabilityReport.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.FAIRNESS_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.FAIRNESS_REPORT],
        parse=lambda path, art, reader: FairnessReport.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.FEATURE_SELECTION_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.FEATURE_SELECTION_EVIDENCE],
        parse=lambda path, art, reader: FeatureSelectionEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.FROZEN_SCORECARD_BUNDLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.FROZEN_SCORECARD_BUNDLE],
        parse=lambda path, art, reader: read_json_payload(path),
    ),
    EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE],
        parse=lambda path, art, reader: HyperparameterTuningEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.IV_TABLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.IV_TABLE],
        parse=lambda path, art, reader: IvTable(
            dataframe=pl.scan_parquet(path),
            columns=pl.scan_parquet(path).collect_schema().names(),
            source_artifact_id=art.artifact_id,
        ),
    ),
    EvidenceKind.MANUAL_BINNING_OVERRIDES: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.MANUAL_BINNING_OVERRIDES],
        parse=lambda path, art, reader: ManualBinningOverrides.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.MODELLING_METADATA: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.MODELLING_METADATA],
        parse=lambda path, art, reader: ModellingMetadata.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.MODEL_ARTIFACT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.MODEL_ARTIFACT],
        parse=lambda path, art, reader: ModelArtifactV1.from_dict(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.PROFILE_SUMMARY: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.PROFILE_SUMMARY],
        parse=lambda path, art, reader: ProfileSummary.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.PROXY_RISK_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.PROXY_RISK_REPORT],
        parse=lambda path, art, reader: ProxyRiskReport.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.REJECT_INFERENCE_RESULT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.REJECT_INFERENCE_RESULT],
        parse=lambda path, art, reader: RejectInferenceResult.from_json(read_json_payload(path)),
    ),
    EvidenceKind.REJECT_POPULATION_CONFIG: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.REJECT_POPULATION_CONFIG],
        parse=lambda path, art, reader: RejectPopulationConfig.from_json(read_json_payload(path)),
    ),
    EvidenceKind.REPORT_BUNDLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.REPORT_BUNDLE],
        parse=lambda path, art, reader: ReportBundleEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.RESAMPLING_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.RESAMPLING_EVIDENCE],
        parse=lambda path, art, reader: ResamplingEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SAMPLE_DEFINITION: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SAMPLE_DEFINITION],
        parse=lambda path, art, reader: SampleDefinition.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SCORED_DATASET: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORED_DATASET],
        parse=lambda path, art, reader: ScoredDataset(dataframe=pl.scan_parquet(path)),
    ),
    EvidenceKind.SCORE_SCALING: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORE_SCALING],
        parse=lambda path, art, reader: ScoreScaling.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SELECTION_DEFINITION: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SELECTION_DEFINITION],
        parse=lambda path, art, reader: SelectionDefinition.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SPLIT_SUMMARY: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SPLIT_SUMMARY],
        parse=lambda path, art, reader: SplitSummary.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.RUN_SUMMARY: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.RUN_SUMMARY],
        parse=lambda path, art, reader: read_json_payload(path),
    ),
    EvidenceKind.TECHNICAL_MANIFEST_INDEX: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.TECHNICAL_MANIFEST_INDEX],
        parse=lambda path, art, reader: TechnicalManifestIndex.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VALIDATION_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VALIDATION_EVIDENCE],
        parse=lambda path, art, reader: ValidationMetrics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VALIDATION_METRICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VALIDATION_METRICS],
        parse=lambda path, art, reader: ValidationMetrics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VARIABLE_CLUSTERING: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VARIABLE_CLUSTERING],
        parse=lambda path, art, reader: VariableClusteringEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.WOE_IV_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.WOE_IV_EVIDENCE],
        parse=lambda path, art, reader: WoeIvEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.WOE_TABLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.WOE_TABLE],
        parse=lambda path, art, reader: _parse_woe_table(path, art),
    ),
    EvidenceKind.WOE_TRANSFORM_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.WOE_TRANSFORM_EVIDENCE],
        parse=lambda path, art, reader: WoeTransformEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.APPLY_WOE_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.APPLY_WOE_EVIDENCE],
        parse=lambda path, art, reader: ApplyWoeEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.APPLY_MODEL_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.APPLY_MODEL_EVIDENCE],
        parse=lambda path, art, reader: ApplyModelEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SCORE_TABLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORE_TABLE],
        parse=lambda path, art, reader: read_json_payload(path),
    ),
    EvidenceKind.SCORING_EXPORT_PYTHON: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORING_EXPORT_PYTHON],
        parse=lambda path, art, reader: read_json_payload(path),
    ),
    EvidenceKind.SCORING_EXPORT_SQL: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORING_EXPORT_SQL],
        parse=lambda path, art, reader: read_json_payload(path),
    ),
    EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS],
        parse=lambda path, art, reader: CoefficientSignDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SEPARATION_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SEPARATION_DIAGNOSTICS],
        parse=lambda path, art, reader: SeparationDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VIF_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VIF_DIAGNOSTICS],
        parse=lambda path, art, reader: VifDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.CALIBRATION_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.CALIBRATION_DIAGNOSTICS],
        parse=lambda path, art, reader: CalibrationDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
}


def _parse_woe_table(path: Path, art: ArtifactRef) -> WoeTable:
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


def get_adapter(kind: EvidenceKind) -> AdapterSpec:
    spec = EVIDENCE_ADAPTERS.get(kind)
    if spec is None:
        raise EvidenceParseError(f"No adapter registered for evidence kind {kind.value}")
    return spec


# ------------------------------------------------------------------
# Matching helpers (formerly in _base.py)
# ------------------------------------------------------------------

def match_by_schema_version(artifacts: list[ArtifactRef], profile: _Profile) -> list[ArtifactRef]:
    if not profile.schema_version:
        return []
    return [a for a in artifacts if a.metadata.get("schema_version") == profile.schema_version]


def match_by_role_type_media(artifacts: list[ArtifactRef], profile: _Profile) -> list[ArtifactRef]:
    return [
        a for a in artifacts
        if a.role in profile.expected_roles
        and a.artifact_type in profile.expected_artifact_types
        and a.media_type in profile.expected_media_types
        and (profile.exclude_key is None or profile.exclude_key not in a.metadata)
    ]


def parquet_has_columns(art: ArtifactRef, columns: set[str], reader: ArtifactReader) -> bool:
    try:
        cols = pl.scan_parquet(reader.resolve_path(art)).collect_schema().names()
        return columns.issubset(cols)
    except Exception:
        return False


def candidate_passes_payload_check(art: ArtifactRef, profile: _Profile, reader: ArtifactReader) -> bool:
    if profile.required_columns is not None:
        if art.media_type == "application/json":
            return False
        return parquet_has_columns(art, profile.required_columns, reader)
    if profile.required_keys:
        path = reader.resolve_path(art)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            keys = set(data.keys())
            return profile.required_keys.issubset(keys)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
    return True


def match(artifacts: list[ArtifactRef], profile: _Profile, reader: ArtifactReader) -> list[ArtifactRef]:
    schema_matches = match_by_schema_version(artifacts, profile)
    if schema_matches:
        return schema_matches
    candidates = match_by_role_type_media(artifacts, profile)
    if len(candidates) == 1:
        if candidate_passes_payload_check(candidates[0], profile, reader):
            return candidates
        candidates = []
    return candidates

def read_json_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def scan_parquet(path: Path) -> Any:
    return pl.scan_parquet(path)


__all__ = [
    "AdapterSpec",
    "EVIDENCE_ADAPTERS",
    "get_adapter",
    "match",
    "match_by_schema_version",
    "match_by_role_type_media",
    "parquet_has_columns",
    "candidate_passes_payload_check",
    "read_json_payload",
    "scan_parquet",
]
