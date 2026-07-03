"""Cardre v2 domain kernel — no I/O dependencies.

Re-exports the five first-class domain concepts plus supporting types.
"""

from cardre.domain.artifacts import (
    ArtifactRef,
    json_logical_hash,
    params_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.domain.diagnostics import JsonDict, parse_iso, utc_now_iso
from cardre.domain.errors import (
    CardreError,
    Diagnostic,
    GovernanceNotEnabled,
    GraphValidationError,
    NodeNotAvailableForLaunch,
    OptionalDependencyNotInstalled,
    PlanContainsUnavailableNodesError,
    PlanVersionNotCommittedError,
    RunLifecycleError,
    RunNotFoundError,
    RunNotRunningError,
    RunPlanVersionMismatchError,
    SchemaVersionError,
)
from cardre.domain.evidence import EvidenceArtifact, EvidenceEdge, ResolvedEvidence
from cardre.domain.manual_binning import ManualBinningReview
from cardre.domain.plan import Plan, PlanVersion
from cardre.domain.project import Project
from cardre.domain.run import Run, RunScope, RunStep, RunStepEvidenceView, RunStepStatus
from cardre.domain.step import StepSpec

__all__ = [
    "ArtifactRef",
    "CardreError",
    "Diagnostic",
    "EvidenceArtifact",
    "EvidenceEdge",
    "GovernanceNotEnabled",
    "GraphValidationError",
    "JsonDict",
    "ManualBinningReview",
    "NodeNotAvailableForLaunch",
    "OptionalDependencyNotInstalled",
    "Plan",
    "PlanContainsUnavailableNodesError",
    "PlanVersion",
    "PlanVersionNotCommittedError",
    "Project",
    "ResolvedEvidence",
    "Run",
    "RunLifecycleError",
    "RunNotFoundError",
    "RunNotRunningError",
    "RunPlanVersionMismatchError",
    "RunScope",
    "RunStep",
    "RunStepEvidenceView",
    "RunStepStatus",
    "SchemaVersionError",
    "StepSpec",
    "json_logical_hash",
    "params_hash",
    "parse_iso",
    "physical_hash",
    "relative_path",
    "table_logical_hash",
    "utc_now_iso",
]
