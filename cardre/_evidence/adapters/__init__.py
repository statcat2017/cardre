"""EvidenceAdapter protocol, registry, and factory.

This package defines the ``EvidenceAdapter`` seam. Each adapter owns
matching and parsing for a single ``EvidenceKind`` and is independent of
``ArtifactEvidenceReader``. The reader will be wired to dispatch through
``EVIDENCE_ADAPTERS`` in a subsequent phase.

Phase 2 is parity-preserving: adapters reproduce the current reader's
three-phase matching (schema-version → role/type/media → legacy payload
heuristics) so behaviour is identical. Legacy payload-key fallbacks
exist because the current reader has them; a later phase will remove
them once all evidence producers emit schema_version consistently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cardre.domain.artifacts import ArtifactRef
from cardre._evidence.kinds import EvidenceKind, EvidenceParseError
from cardre._evidence.profiles import _Profile
from cardre.store import ProjectStore


@runtime_checkable
class EvidenceAdapter(Protocol):
    kind: EvidenceKind
    profile: _Profile

    def match(self, artifacts: list[ArtifactRef], store: ProjectStore) -> list[ArtifactRef]: ...
    def parse(self, path: Path, art: ArtifactRef, store: ProjectStore) -> Any: ...


from cardre._evidence.adapters.binning import (
    BinDefinitionAdapter,
    ManualBinningOverridesAdapter,
    SelectionDefinitionAdapter,
)
from cardre._evidence.adapters.governance import (
    ExplainabilityReportAdapter,
    FairnessReportAdapter,
    FeatureSelectionEvidenceAdapter,
    HyperparameterTuningEvidenceAdapter,
    ProxyRiskReportAdapter,
    RejectInferenceResultAdapter,
    RejectPopulationConfigAdapter,
    ResamplingEvidenceAdapter,
    VariableClusteringAdapter,
)
from cardre._evidence.adapters.manifest import (
    ComparisonArtifactAdapter,
    ReportBundleAdapter,
    RunManifestAdapter,
    TechnicalManifestIndexAdapter,
)
from cardre._evidence.adapters.model import (
    EnsembleModelArtifactAdapter,
    FrozenScorecardBundleAdapter,
    ModelArtifactAdapter,
    ScoreScalingAdapter,
)
from cardre._evidence.adapters.sample import (
    ExclusionSummaryAdapter,
    ModellingMetadataAdapter,
    ProfileSummaryAdapter,
    SampleDefinitionAdapter,
    SplitSummaryAdapter,
)
from cardre._evidence.adapters.validation import (
    CalibrationReportAdapter,
    CutoffAnalysisAdapter,
    ValidationEvidenceAdapter,
    ValidationMetricsAdapter,
)
from cardre._evidence.adapters.woe import (
    ApplyModelEvidenceAdapter,
    ApplyWoeEvidenceAdapter,
    IvTableAdapter,
    ScoredDatasetAdapter,
    WoeIvEvidenceAdapter,
    WoeTableAdapter,
    WoeTransformEvidenceAdapter,
)

EVIDENCE_ADAPTERS: dict[EvidenceKind, type[EvidenceAdapter]] = {
    EvidenceKind.BIN_DEFINITION: BinDefinitionAdapter,
    EvidenceKind.CALIBRATION_REPORT: CalibrationReportAdapter,
    EvidenceKind.COMPARISON_ARTIFACT: ComparisonArtifactAdapter,
    EvidenceKind.CUTOFF_ANALYSIS: CutoffAnalysisAdapter,
    EvidenceKind.ENSEMBLE_MODEL_ARTIFACT: EnsembleModelArtifactAdapter,
    EvidenceKind.EXCLUSION_SUMMARY: ExclusionSummaryAdapter,
    EvidenceKind.EXPLAINABILITY_REPORT: ExplainabilityReportAdapter,
    EvidenceKind.FAIRNESS_REPORT: FairnessReportAdapter,
    EvidenceKind.FEATURE_SELECTION_EVIDENCE: FeatureSelectionEvidenceAdapter,
    EvidenceKind.FROZEN_SCORECARD_BUNDLE: FrozenScorecardBundleAdapter,
    EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE: HyperparameterTuningEvidenceAdapter,
    EvidenceKind.IV_TABLE: IvTableAdapter,
    EvidenceKind.MANUAL_BINNING_OVERRIDES: ManualBinningOverridesAdapter,
    EvidenceKind.MODELLING_METADATA: ModellingMetadataAdapter,
    EvidenceKind.MODEL_ARTIFACT: ModelArtifactAdapter,
    EvidenceKind.PROFILE_SUMMARY: ProfileSummaryAdapter,
    EvidenceKind.PROXY_RISK_REPORT: ProxyRiskReportAdapter,
    EvidenceKind.REJECT_INFERENCE_RESULT: RejectInferenceResultAdapter,
    EvidenceKind.REJECT_POPULATION_CONFIG: RejectPopulationConfigAdapter,
    EvidenceKind.REPORT_BUNDLE: ReportBundleAdapter,
    EvidenceKind.RESAMPLING_EVIDENCE: ResamplingEvidenceAdapter,
    EvidenceKind.RUN_MANIFEST: RunManifestAdapter,
    EvidenceKind.SAMPLE_DEFINITION: SampleDefinitionAdapter,
    EvidenceKind.SCORED_DATASET: ScoredDatasetAdapter,
    EvidenceKind.SCORE_SCALING: ScoreScalingAdapter,
    EvidenceKind.SELECTION_DEFINITION: SelectionDefinitionAdapter,
    EvidenceKind.SPLIT_SUMMARY: SplitSummaryAdapter,
    EvidenceKind.TECHNICAL_MANIFEST_INDEX: TechnicalManifestIndexAdapter,
    EvidenceKind.VALIDATION_EVIDENCE: ValidationEvidenceAdapter,
    EvidenceKind.VALIDATION_METRICS: ValidationMetricsAdapter,
    EvidenceKind.VARIABLE_CLUSTERING: VariableClusteringAdapter,
    EvidenceKind.WOE_IV_EVIDENCE: WoeIvEvidenceAdapter,
    EvidenceKind.WOE_TABLE: WoeTableAdapter,
    EvidenceKind.WOE_TRANSFORM_EVIDENCE: WoeTransformEvidenceAdapter,
    EvidenceKind.APPLY_WOE_EVIDENCE: ApplyWoeEvidenceAdapter,
    EvidenceKind.APPLY_MODEL_EVIDENCE: ApplyModelEvidenceAdapter,
}


def get_adapter(kind: EvidenceKind) -> EvidenceAdapter:
    cls = EVIDENCE_ADAPTERS.get(kind)
    if cls is None:
        raise EvidenceParseError(f"No adapter registered for evidence kind {kind.value}")
    return cls()
