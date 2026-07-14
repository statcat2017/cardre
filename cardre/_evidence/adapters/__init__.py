"""EvidenceAdapter protocol, registry, and factory.

Replaces 40 adapter classes with a ``dict[EvidenceKind, AdapterSpec]`` table.
Each entry wires a profile to a parse callable. The shared ``match`` function
lives in ``_base.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from cardre._evidence.adapters._base import read_json_payload
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
from cardre._evidence.models.model import ModelArtifact, ScoreScaling
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
from cardre.domain.artifacts import ArtifactRef
from cardre.store import ProjectStore


@dataclass(frozen=True)
class AdapterSpec:
    profile: _Profile
    parse: Callable[[Path, ArtifactRef, ProjectStore], Any]


EVIDENCE_ADAPTERS: dict[EvidenceKind, AdapterSpec] = {
    EvidenceKind.BIN_DEFINITION: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.BIN_DEFINITION],
        parse=lambda path, art, store: BinDefinition.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.CALIBRATION_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.CALIBRATION_REPORT],
        parse=lambda path, art, store: read_json_payload(path),
    ),
    EvidenceKind.COMPARISON_ARTIFACT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.COMPARISON_ARTIFACT],
        parse=lambda path, art, store: ComparisonArtifact.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.CUTOFF_ANALYSIS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.CUTOFF_ANALYSIS],
        parse=lambda path, art, store: CutoffAnalysis.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.ENSEMBLE_MODEL_ARTIFACT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.ENSEMBLE_MODEL_ARTIFACT],
        parse=lambda path, art, store: ModelArtifact.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.EXCLUSION_SUMMARY: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.EXCLUSION_SUMMARY],
        parse=lambda path, art, store: ExclusionSummary.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.EXPLAINABILITY_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.EXPLAINABILITY_REPORT],
        parse=lambda path, art, store: ExplainabilityReport.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.FAIRNESS_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.FAIRNESS_REPORT],
        parse=lambda path, art, store: FairnessReport.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.FEATURE_SELECTION_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.FEATURE_SELECTION_EVIDENCE],
        parse=lambda path, art, store: FeatureSelectionEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.FROZEN_SCORECARD_BUNDLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.FROZEN_SCORECARD_BUNDLE],
        parse=lambda path, art, store: read_json_payload(path),
    ),
    EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE],
        parse=lambda path, art, store: HyperparameterTuningEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.IV_TABLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.IV_TABLE],
        parse=lambda path, art, store: IvTable(
            dataframe=pl.scan_parquet(path),
            columns=pl.scan_parquet(path).collect_schema().names(),
            source_artifact_id=art.artifact_id,
        ),
    ),
    EvidenceKind.MANUAL_BINNING_OVERRIDES: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.MANUAL_BINNING_OVERRIDES],
        parse=lambda path, art, store: ManualBinningOverrides.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.MODELLING_METADATA: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.MODELLING_METADATA],
        parse=lambda path, art, store: ModellingMetadata.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.MODEL_ARTIFACT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.MODEL_ARTIFACT],
        parse=lambda path, art, store: ModelArtifact.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.PROFILE_SUMMARY: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.PROFILE_SUMMARY],
        parse=lambda path, art, store: ProfileSummary.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.PROXY_RISK_REPORT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.PROXY_RISK_REPORT],
        parse=lambda path, art, store: ProxyRiskReport.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.REJECT_INFERENCE_RESULT: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.REJECT_INFERENCE_RESULT],
        parse=lambda path, art, store: RejectInferenceResult.from_json(read_json_payload(path)),
    ),
    EvidenceKind.REJECT_POPULATION_CONFIG: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.REJECT_POPULATION_CONFIG],
        parse=lambda path, art, store: RejectPopulationConfig.from_json(read_json_payload(path)),
    ),
    EvidenceKind.REPORT_BUNDLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.REPORT_BUNDLE],
        parse=lambda path, art, store: ReportBundleEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.RESAMPLING_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.RESAMPLING_EVIDENCE],
        parse=lambda path, art, store: ResamplingEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SAMPLE_DEFINITION: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SAMPLE_DEFINITION],
        parse=lambda path, art, store: SampleDefinition.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SCORED_DATASET: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORED_DATASET],
        parse=lambda path, art, store: ScoredDataset(dataframe=pl.scan_parquet(path)),
    ),
    EvidenceKind.SCORE_SCALING: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORE_SCALING],
        parse=lambda path, art, store: ScoreScaling.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SELECTION_DEFINITION: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SELECTION_DEFINITION],
        parse=lambda path, art, store: SelectionDefinition.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SPLIT_SUMMARY: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SPLIT_SUMMARY],
        parse=lambda path, art, store: SplitSummary.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.TECHNICAL_MANIFEST_INDEX: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.TECHNICAL_MANIFEST_INDEX],
        parse=lambda path, art, store: TechnicalManifestIndex.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VALIDATION_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VALIDATION_EVIDENCE],
        parse=lambda path, art, store: ValidationMetrics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VALIDATION_METRICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VALIDATION_METRICS],
        parse=lambda path, art, store: ValidationMetrics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VARIABLE_CLUSTERING: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VARIABLE_CLUSTERING],
        parse=lambda path, art, store: VariableClusteringEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.WOE_IV_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.WOE_IV_EVIDENCE],
        parse=lambda path, art, store: WoeIvEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.WOE_TABLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.WOE_TABLE],
        parse=lambda path, art, store: _parse_woe_table(path, art),
    ),
    EvidenceKind.WOE_TRANSFORM_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.WOE_TRANSFORM_EVIDENCE],
        parse=lambda path, art, store: WoeTransformEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.APPLY_WOE_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.APPLY_WOE_EVIDENCE],
        parse=lambda path, art, store: ApplyWoeEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.APPLY_MODEL_EVIDENCE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.APPLY_MODEL_EVIDENCE],
        parse=lambda path, art, store: ApplyModelEvidence.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SCORE_TABLE: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORE_TABLE],
        parse=lambda path, art, store: read_json_payload(path),
    ),
    EvidenceKind.SCORING_EXPORT_PYTHON: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORING_EXPORT_PYTHON],
        parse=lambda path, art, store: read_json_payload(path),
    ),
    EvidenceKind.SCORING_EXPORT_SQL: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SCORING_EXPORT_SQL],
        parse=lambda path, art, store: read_json_payload(path),
    ),
    EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.COEFFICIENT_SIGN_DIAGNOSTICS],
        parse=lambda path, art, store: CoefficientSignDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.SEPARATION_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.SEPARATION_DIAGNOSTICS],
        parse=lambda path, art, store: SeparationDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.VIF_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.VIF_DIAGNOSTICS],
        parse=lambda path, art, store: VifDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
    ),
    EvidenceKind.CALIBRATION_DIAGNOSTICS: AdapterSpec(
        profile=EVIDENCE_PROFILES[EvidenceKind.CALIBRATION_DIAGNOSTICS],
        parse=lambda path, art, store: CalibrationDiagnostics.from_json(read_json_payload(path), artifact_id=art.artifact_id),
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


__all__ = [
    "AdapterSpec",
    "EVIDENCE_ADAPTERS",
    "get_adapter",
]
