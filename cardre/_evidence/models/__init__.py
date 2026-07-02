"""Typed evidence data models — split by family."""

from cardre._evidence.models.apply import ApplyModelEvidence, ApplyWoeEvidence, ScoredDataset
from cardre._evidence.models.binning import BinDefinition, BinVariable, SelectedVariable, SelectionDefinition
from cardre._evidence.models.governance import (
    ClusterMember,
    ExplainabilityReport,
    FairnessReport,
    FeatureSelectionEvidence,
    HyperparameterTuningEvidence,
    ProxyRiskReport,
    RejectInferenceResult,
    RejectPopulationConfig,
    ResamplingEvidence,
    VariableCluster,
    VariableClusteringEvidence,
)
from cardre._evidence.models.manifest import (
    ComparisonArtifact,
    ReportBundleEvidence,
    RunManifestEvidence,
    TechnicalManifestIndex,
)
from cardre._evidence.models.model import Coefficient, ModelArtifact, ScoreScaling
from cardre._evidence.models.sample import (
    ExclusionSummary,
    ModellingMetadata,
    ProfileSummary,
    SampleDefinition,
    SplitSummary,
)
from cardre._evidence.models.summary import ArtifactEvidenceSummary
from cardre._evidence.models.validation import CutoffAnalysis, CutoffRow, RoleMetrics, ValidationMetrics
from cardre._evidence.models.woe import (
    AffectedBin,
    IvTable,
    WoeBin,
    WoeIvEvidence,
    WoeIvVariable,
    WoeSmoothing,
    WoeTable,
    WoeTransformEvidence,
)

__all__ = [
    "AffectedBin",
    "ApplyModelEvidence",
    "ApplyWoeEvidence",
    "ArtifactEvidenceSummary",
    "BinDefinition",
    "BinVariable",
    "ClusterMember",
    "Coefficient",
    "ComparisonArtifact",
    "CutoffAnalysis",
    "CutoffRow",
    "ExclusionSummary",
    "ExplainabilityReport",
    "FairnessReport",
    "FeatureSelectionEvidence",
    "HyperparameterTuningEvidence",
    "IvTable",
    "ModelArtifact",
    "ModellingMetadata",
    "ProfileSummary",
    "ProxyRiskReport",
    "RejectInferenceResult",
    "RejectPopulationConfig",
    "ReportBundleEvidence",
    "ResamplingEvidence",
    "RoleMetrics",
    "RunManifestEvidence",
    "SampleDefinition",
    "ScoreScaling",
    "ScoredDataset",
    "SelectedVariable",
    "SelectionDefinition",
    "SplitSummary",
    "TechnicalManifestIndex",
    "ValidationMetrics",
    "VariableCluster",
    "VariableClusteringEvidence",
    "WoeBin",
    "WoeIvEvidence",
    "WoeIvVariable",
    "WoeSmoothing",
    "WoeTable",
    "WoeTransformEvidence",
]
