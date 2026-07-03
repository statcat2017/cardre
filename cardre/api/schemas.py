"""Pydantic models for the Cardre v2 API — full surface.

Every response follows a consistent shape.  Governance-gated routes always
return ``GOVERNANCE_DISABLED`` (403) when ``CARDRE_GOVERNANCE=0``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cardre._version import __version__

# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    code: str
    message: str
    context: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: ErrorDetail


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectResponse(BaseModel):
    project_id: str
    name: str
    created_at: str
    cardre_version: str


class UnavailableProjectResponse(BaseModel):
    """A registered project that could not be opened (corrupt, missing, etc)."""
    project_id: str
    root: str
    code: str
    message: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    unavailable_projects: list[UnavailableProjectResponse] = Field(default_factory=list)


class ProjectCreateRequest(BaseModel):
    name: str
    path: str


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class PlanResponse(BaseModel):
    plan_id: str
    project_id: str
    name: str
    created_at: str


class PlanListResponse(BaseModel):
    plans: list[PlanResponse]


class PlanCreateRequest(BaseModel):
    name: str


class PlanVersionResponse(BaseModel):
    plan_version_id: str
    plan_id: str
    version_number: int
    is_committed: bool
    created_at: str
    description: str = ""


class PlanVersionListResponse(BaseModel):
    versions: list[PlanVersionResponse]


class PlanVersionUpdate(BaseModel):
    description: str | None = None


class PlanStepResponse(BaseModel):
    step_id: str
    plan_version_id: str
    node_type: str
    node_version: str
    category: str
    params: dict = Field(default_factory=dict)
    params_hash: str = ""
    parent_step_ids: list[str] = Field(default_factory=list)
    branch_label: str = ""
    position: int = 0
    canonical_step_id: str = ""
    branch_id: str | None = None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class RunResponse(BaseModel):
    run_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    step_count: int = 0
    branch_id: str | None = None
    executed_step_ids: list[str] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    latest_error: dict | None = None
    heartbeat_at: str | None = None
    is_stale: bool = False


class RunListResponse(BaseModel):
    runs: list[RunResponse]


class RunCreateRequest(BaseModel):
    plan_version_id: str
    force: bool = False
    sync: bool = False


class RunStepResponse(BaseModel):
    run_step_id: str
    run_id: str
    step_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    execution_fingerprint: dict = Field(default_factory=dict)
    warnings: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceEdgeResponse(BaseModel):
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
    is_reused: bool = False
    is_stale: bool = False
    stale_reason: str | None = None
    created_at: str = ""


class EvidenceArtifactResponse(BaseModel):
    evidence_artifact_id: str
    evidence_edge_id: str
    artifact_id: str
    role: str
    created_at: str = ""


class ResolvedEvidenceResponse(BaseModel):
    run_step_id: str
    edges: list[EvidenceEdgeResponse]
    artifacts: list[EvidenceArtifactResponse]


class RunEvidenceEdgeResponse(BaseModel):
    """Typed response for a single evidence edge in a run (#216).

    Includes full provenance fields from EvidenceEdgeResponse plus
    nested artifacts so the generated schema and frontend types match
    the actual payload shape.
    """
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
    is_reused: bool = False
    is_stale: bool = False
    stale_reason: str | None = None
    created_at: str = ""
    artifacts: list[EvidenceArtifactResponse] = Field(default_factory=list)


class StalenessExplanationResponse(BaseModel):
    step_id: str
    status: str  # "fresh", "stale", "missing"
    upstream_changes: dict[str, bool]
    missing_evidence: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class ArtifactResponse(BaseModel):
    artifact_id: str
    artifact_type: str
    role: str
    path: str
    physical_hash: str
    logical_hash: str
    media_type: str
    created_at: str


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactResponse]


# ---------------------------------------------------------------------------
# Manual Binning
# ---------------------------------------------------------------------------

class ManualBinningReviewResponse(BaseModel):
    review_id: str
    plan_version_id: str
    step_id: str
    status: str
    reviewer_notes: str = ""
    affected_downstream_step_ids: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class ManualBinningReviewUpdate(BaseModel):
    status: str | None = None
    reviewer_notes: str | None = None


class ManualBinningEditRequest(BaseModel):
    plan_version_id: str
    step_id: str
    overrides: list[dict] = Field(default_factory=list)
    reviewer_notes: str = ""
    status: str = "pending"
    affected_downstream_step_ids: list[str] = Field(default_factory=list)


class ManualBinningEditResponse(BaseModel):
    new_plan_version_id: str
    review_id: str
    affected_step_ids: list[str] = Field(default_factory=list)


class ManualBinningPreviewRequest(BaseModel):
    variable_data: dict


class ManualBinningPreviewResponse(BaseModel):
    woe_by_bin: list[dict]
    iv: float
    event_rate_by_bin: list[dict]


# ---------------------------------------------------------------------------
# Branches (governance-gated)
# ---------------------------------------------------------------------------

class BranchResponse(BaseModel):
    branch_id: str
    project_id: str
    plan_id: str
    name: str
    description: str | None = None
    branch_type: str
    status: str = "active"
    base_branch_id: str | None = None
    base_plan_version_id: str
    head_plan_version_id: str
    branch_point_step_id: str | None = None
    branch_point_canonical_step_id: str | None = None
    created_reason: str = ""
    created_at: str = ""
    updated_at: str = ""


class BranchListResponse(BaseModel):
    branches: list[BranchResponse]


class BranchCreateRequest(BaseModel):
    plan_id: str
    name: str
    branch_type: str = "challenger"
    base_plan_version_id: str
    head_plan_version_id: str
    description: str | None = None
    base_branch_id: str | None = None
    branch_point_step_id: str | None = None
    created_reason: str = ""


# ---------------------------------------------------------------------------
# Comparisons (governance-gated)
# ---------------------------------------------------------------------------

class ComparisonResponse(BaseModel):
    comparison_id: str
    project_id: str
    plan_id: str
    baseline_branch_id: str
    created_at: str = ""
    latest_ready: bool | None = None


class ComparisonListResponse(BaseModel):
    comparisons: list[ComparisonResponse]


# ---------------------------------------------------------------------------
# Champion (governance-gated)
# ---------------------------------------------------------------------------

class ChampionAssignmentResponse(BaseModel):
    champion_assignment_id: str
    project_id: str
    plan_id: str
    champion_branch_id: str
    selected_plan_version_id: str
    assigned_at: str = ""
    superseded_at: str | None = None


class ChampionResponse(BaseModel):
    assignment: ChampionAssignmentResponse | None = None


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeTypeResponse(BaseModel):
    node_type: str
    display_name: str = ""
    description: str = ""
    category: str = ""
    tier: str = "launch"
    has_params: bool = False


class NodeTypeListResponse(BaseModel):
    node_types: list[NodeTypeResponse]


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

class ExportResponse(BaseModel):
    export_id: str
    run_id: str
    export_type: str
    path: str
    created_at: str
    size_bytes: int = 0


class ExportListResponse(BaseModel):
    exports: list[ExportResponse]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class ReportResponse(BaseModel):
    report_id: str
    run_id: str | None = None
    report_type: str
    path: str
    created_at: str


class ReportListResponse(BaseModel):
    reports: list[ReportResponse]


__all__ = [
    "ArtifactListResponse",
    "ArtifactResponse",
    "BranchCreateRequest",
    "BranchListResponse",
    "BranchResponse",
    "ChampionAssignmentResponse",
    "ChampionResponse",
    "ComparisonListResponse",
    "ComparisonResponse",
    "ErrorDetail",
    "ErrorResponse",
    "EvidenceArtifactResponse",
    "EvidenceEdgeResponse",
    "ExportListResponse",
    "ExportResponse",
    "HealthResponse",
    "ManualBinningEditRequest",
    "ManualBinningEditResponse",
    "ManualBinningPreviewRequest",
    "ManualBinningPreviewResponse",
    "ManualBinningReviewResponse",
    "ManualBinningReviewUpdate",
    "NodeTypeListResponse",
    "NodeTypeResponse",
    "PlanCreateRequest",
    "PlanListResponse",
    "PlanResponse",
    "PlanStepResponse",
    "PlanVersionListResponse",
    "PlanVersionResponse",
    "PlanVersionUpdate",
    "ProjectCreateRequest",
    "ProjectListResponse",
    "ProjectResponse",
    "UnavailableProjectResponse",
    "ReportListResponse",
    "ReportResponse",
    "ResolvedEvidenceResponse",
    "RunCreateRequest",
    "RunEvidenceEdgeResponse",
    "RunListResponse",
    "RunResponse",
    "RunStepResponse",
    "StalenessExplanationResponse",
]
