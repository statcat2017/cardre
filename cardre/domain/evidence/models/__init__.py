"""Typed evidence data models — split by family."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cardre.domain.diagnostics import JsonDict

if TYPE_CHECKING:
    from cardre.domain.run import RunStep


from cardre.domain.evidence.models.apply import ApplyModelEvidence, ApplyWoeEvidence, ScoredDataset
from cardre.domain.evidence.models.binning import (
    BinDefinition,
    BinVariable,
    ManualBinningOverride,
    ManualBinningOverrides,
    SelectedVariable,
    SelectionDefinition,
)
from cardre.domain.evidence.models.diagnostics import (
    CalibrationBin,
    CalibrationDiagnostics,
    CalibrationRole,
    CoefficientSignDiagnostics,
    CoefficientSignEntry,
    SeparationDiagnostics,
    SeparationEntry,
    VifDiagnostics,
    VifEntry,
)
from cardre.domain.evidence.models.governance import (
    ClusterMember,
    ExplainabilityReport,
    FairnessReport,
    FeatureSelectionEvidence,
    HyperparameterTuningEvidence,
    LimitationItem,
    ProxyRiskReport,
    RejectInferenceResult,
    RejectPopulationConfig,
    ResamplingEvidence,
    VariableCluster,
    VariableClusteringEvidence,
)
from cardre.domain.evidence.models.manifest import (
    ComparisonArtifact,
    ReportBundleEvidence,
    TechnicalManifestIndex,
)
from cardre.domain.evidence.models.model import ScoreScaling
from cardre.domain.evidence.models.sample import (
    ExclusionSummary,
    ModellingMetadata,
    ProfileSummary,
    SampleDefinition,
    SplitSummary,
)
from cardre.domain.evidence.models.summary import ArtifactEvidenceSummary
from cardre.domain.evidence.models.validation import (
    CutoffAnalysis,
    CutoffRow,
    RoleMetrics,
    ValidationMetrics,
)
from cardre.domain.evidence.models.woe import (
    AffectedBin,
    IvTable,
    WoeBin,
    WoeIvEvidence,
    WoeIvVariable,
    WoeSmoothing,
    WoeTable,
    WoeTransformEvidence,
)


@dataclass(frozen=True)
class EvidenceEdge:
    evidence_edge_id: str
    run_id: str
    run_step_id: str
    plan_version_id: str
    step_id: str
    parent_step_id: str
    source_run_id: str
    source_run_step_id: str
    policy: str
    source_label: str
    is_reused: bool
    is_stale: bool
    stale_reason: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class EvidenceArtifact:
    evidence_artifact_id: str
    evidence_edge_id: str
    artifact_id: str
    role: str
    created_at: str = ""


@dataclass(frozen=True)
class ResolvedEvidence:
    run_step_id: str
    run_step: RunStep
    edges: list[EvidenceEdge]
    artifacts: list[EvidenceArtifact]
    source_label: str = ""

    def input_artifact_ids(self) -> list[str]:
        return [ea.artifact_id for ea in self.artifacts]

    def edge_for_artifact(self, artifact_id: str) -> EvidenceEdge | None:
        for ea in self.artifacts:
            if ea.artifact_id == artifact_id:
                for e in self.edges:
                    if e.evidence_edge_id == ea.evidence_edge_id:
                        return e
        return None

    def to_dict(self) -> JsonDict:
        return {
            "run_step_id": self.run_step_id,
            "run_step": {
                "run_step_id": self.run_step.run_step_id,
                "run_id": self.run_step.run_id,
                "step_id": self.run_step.step_id,
                "plan_version_id": self.run_step.plan_version_id,
                "status": self.run_step.status.value,
                "started_at": self.run_step.started_at,
                "finished_at": self.run_step.finished_at,
                "execution_fingerprint": self.run_step.execution_fingerprint,
                "warnings": self.run_step.warnings,
                "errors": self.run_step.errors,
            },
            "edges": [
                {
                    "evidence_edge_id": e.evidence_edge_id,
                    "run_id": e.run_id,
                    "run_step_id": e.run_step_id,
                    "plan_version_id": e.plan_version_id,
                    "step_id": e.step_id,
                    "parent_step_id": e.parent_step_id,
                    "source_run_id": e.source_run_id,
                    "source_run_step_id": e.source_run_step_id,
                    "policy": e.policy,
                    "source_label": e.source_label,
                    "is_reused": e.is_reused,
                    "is_stale": e.is_stale,
                    "stale_reason": e.stale_reason,
                    "created_at": e.created_at,
                }
                for e in self.edges
            ],
            "artifacts": [
                {
                    "evidence_artifact_id": ea.evidence_artifact_id,
                    "evidence_edge_id": ea.evidence_edge_id,
                    "artifact_id": ea.artifact_id,
                    "role": ea.role,
                    "created_at": ea.created_at,
                }
                for ea in self.artifacts
            ],
        }



__all__ = [
    "AffectedBin",
    "ApplyModelEvidence",
    "ApplyWoeEvidence",
    "ArtifactEvidenceSummary",
    "BinDefinition",
    "BinVariable",
    "CalibrationBin",
    "CalibrationDiagnostics",
    "CalibrationRole",
    "ClusterMember",
    "CoefficientSignDiagnostics",
    "CoefficientSignEntry",
    "ComparisonArtifact",
    "CutoffAnalysis",
    "CutoffRow",
    "EvidenceArtifact",
    "EvidenceEdge",
    "ExclusionSummary",
    "ExplainabilityReport",
    "FairnessReport",
    "FeatureSelectionEvidence",
    "HyperparameterTuningEvidence",
    "IvTable",
    "LimitationItem",
    "ManualBinningOverride",
    "ManualBinningOverrides",
    "ModellingMetadata",
    "ProfileSummary",
    "ProxyRiskReport",
    "RejectInferenceResult",
    "RejectPopulationConfig",
    "ReportBundleEvidence",
    "ResamplingEvidence",
    "ResolvedEvidence",
    "RoleMetrics",
    "SampleDefinition",
    "ScoreScaling",
    "ScoredDataset",
    "SelectedVariable",
    "SelectionDefinition",
    "SeparationDiagnostics",
    "SeparationEntry",
    "SplitSummary",
    "TechnicalManifestIndex",
    "ValidationMetrics",
    "VariableCluster",
    "VariableClusteringEvidence",
    "VifDiagnostics",
    "VifEntry",
    "WoeBin",
    "WoeIvEvidence",
    "WoeIvVariable",
    "WoeSmoothing",
    "WoeTable",
    "WoeTransformEvidence",
]
