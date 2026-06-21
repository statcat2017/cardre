"""Typed Artifact Evidence Module — backward-compatible re-exports.

Provides typed access to Artifact contents so callers (Node types, reporting,
comparison, Plan service) ask for evidence by meaning rather than by inspecting
file bytes, JSON keys, and column names.

The implementation has been split into submodules under ``cardre/_evidence/``.
This module re-exports the public API for backward compatibility.
"""

from cardre._evidence.schemas import (
    SCHEMA_CUTOFF_ANALYSIS,
    SCHEMA_FROZEN_SCORECARD_BUNDLE,
    SCHEMA_MANUAL_BINNING_OVERRIDES,
    SCHEMA_MODELLING_METADATA,
    SCHEMA_MODEL_ARTIFACT,
    SCHEMA_REJECT_INFERENCE_RESULT,
    SCHEMA_REJECT_POPULATION_CONFIG,
    SCHEMA_SAMPLE_DEFINITION,
    SCHEMA_SCORE_APPLICATION_EVIDENCE,
    SCHEMA_SCORE_SCALING,
    SCHEMA_SELECTION_DEFINITION,
    SCHEMA_VALIDATION_EVIDENCE,
    SCHEMA_VALIDATION_METRICS,
    SCHEMA_VARIABLE_CLUSTERING_EVIDENCE,
    SCHEMA_WOE_APPLICATION_EVIDENCE,
    SCHEMA_WOE_IV_EVIDENCE,
    SCHEMA_WOE_TABLE,
)
from cardre.engine.binning.definition import SCHEMA_BIN_DEFINITION  # noqa: F401
from cardre._evidence.kinds import (
    EvidenceKind,
    EvidenceError,
    EvidenceNotFoundError,
    AmbiguousEvidenceError,
    EvidenceParseError,
)
from cardre._evidence.models import (
    BinVariable,
    BinDefinition,
    Coefficient,
    SelectedVariable,
    SelectionDefinition,
    ModellingMetadata,
    SampleDefinition,
    RejectPopulationConfig,
    RejectInferenceResult,
    WoeIvEvidence,
    ModelArtifact,
    ScoreScaling,
    ValidationMetrics,
    CutoffAnalysis,
    WoeTable,
    IvTable,
    ScoredDataset,
    ClusterMember,
    VariableCluster,
    VariableClusteringEvidence,
)
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.profiles import EVIDENCE_PROFILES as _EVIDENCE_PROFILES  # backward compat

__all__ = [
    "SCHEMA_MODELLING_METADATA",
    "SCHEMA_SAMPLE_DEFINITION",
    "SCHEMA_REJECT_POPULATION_CONFIG",
    "SCHEMA_REJECT_INFERENCE_RESULT",
    "SCHEMA_SELECTION_DEFINITION",
    "SCHEMA_WOE_TABLE",
    "SCHEMA_WOE_IV_EVIDENCE",
    "SCHEMA_VARIABLE_CLUSTERING_EVIDENCE",
    "SCHEMA_MODEL_ARTIFACT",
    "SCHEMA_SCORE_SCALING",
    "SCHEMA_VALIDATION_METRICS",
    "SCHEMA_CUTOFF_ANALYSIS",
    "SCHEMA_MANUAL_BINNING_OVERRIDES",
    "SCHEMA_FROZEN_SCORECARD_BUNDLE",
    "SCHEMA_WOE_APPLICATION_EVIDENCE",
    "SCHEMA_SCORE_APPLICATION_EVIDENCE",
    "SCHEMA_VALIDATION_EVIDENCE",
    "EvidenceKind",
    "EvidenceError",
    "EvidenceNotFoundError",
    "AmbiguousEvidenceError",
    "EvidenceParseError",
    "BinVariable",
    "BinDefinition",
    "Coefficient",
    "SelectedVariable",
    "SelectionDefinition",
    "ModellingMetadata",
    "SampleDefinition",
    "WoeIvEvidence",
    "ModelArtifact",
    "ScoreScaling",
    "ValidationMetrics",
    "CutoffAnalysis",
    "WoeTable",
    "IvTable",
    "ScoredDataset",
    "ArtifactEvidenceReader",
]
