"""Pydantic request/response models for the Cardre sidecar API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    cardre_version: str = "0.1.0"
    registry_accessible: bool = False
    registered_node_count: int = 0
    checked_at: str = ""


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    path: str
    name: str = "Untitled Project"


class ProjectResponse(BaseModel):
    project_id: str
    path: str
    name: str
    created_at: str


class ProjectDetailResponse(ProjectResponse):
    plan_count: int = 0
    run_count: int = 0


# ---------------------------------------------------------------------------
# Datasets / Import
# ---------------------------------------------------------------------------

class ImportDatasetRequest(BaseModel):
    project_id: str
    source_path: str
    dataset_id: str = ""
    format: str = "auto"
    delimiter: str | None = None
    has_header: bool = True
    schema_overrides: dict[str, str] = {}


class ArtifactResponse(BaseModel):
    artifact_id: str
    artifact_type: str
    role: str
    path: str
    physical_hash: str
    logical_hash: str
    media_type: str
    created_at: str
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class StepStatusItem(BaseModel):
    step_id: str
    node_type: str
    category: str
    status: str = "not_run"
    is_stale: bool = False
    position: int = 0
    params: dict[str, Any] = Field(default_factory=dict)
    canonical_step_id: str = ""
    branch_id: str | None = None


class PlanResponse(BaseModel):
    plan_id: str
    project_id: str
    name: str
    latest_version_id: str
    steps: list[StepStatusItem]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    project_id: str
    plan_version_id: str
    run_scope: str = "full_plan"
    branch_id: str | None = None


class RunResponse(BaseModel):
    run_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    step_count: int = 0
    branch_id: str | None = None
    executed_step_ids: list[str] = Field(default_factory=list)


class RunStepItem(BaseModel):
    run_step_id: str
    step_id: str
    node_type: str
    status: str
    started_at: str
    finished_at: str | None = None
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    is_carried_forward: bool = False


class RunStepsResponse(BaseModel):
    run_id: str
    steps: list[RunStepItem]


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


# ---------------------------------------------------------------------------
# Project Plans List
# ---------------------------------------------------------------------------

class PlanListItem(BaseModel):
    plan_id: str
    name: str
    latest_version_id: str
    is_default: bool = False
    is_hidden: bool = False


class ProjectPlansResponse(BaseModel):
    project_id: str
    plans: list[PlanListItem]


# ---------------------------------------------------------------------------
# Plan Step Params Update (Phase 3C)
# ---------------------------------------------------------------------------

class UpdateStepParamsRequest(BaseModel):
    project_id: str
    base_plan_version_id: str
    params: dict[str, Any]


class UpdateStepParamsResponse(BaseModel):
    plan_id: str
    new_plan_version_id: str
    changed_step_id: str
    stale_step_ids: list[str]


# ---------------------------------------------------------------------------
# Project Runs (Phase 3C)
# ---------------------------------------------------------------------------

class RunListItem(BaseModel):
    run_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    step_count: int = 0


class ProjectRunsResponse(BaseModel):
    project_id: str
    runs: list[RunListItem]


# ---------------------------------------------------------------------------
# Project Artifacts (Phase 3D)
# ---------------------------------------------------------------------------

class ArtifactListItem(ArtifactResponse):
    pass


class ProjectArtifactsResponse(BaseModel):
    project_id: str
    artifacts: list[ArtifactListItem]


# ---------------------------------------------------------------------------
# Artifact Summary & Preview (Phase 3D)
# ---------------------------------------------------------------------------

class ArtifactSummaryResponse(BaseModel):
    artifact_id: str
    artifact_type: str
    role: str
    media_type: str
    logical_hash: str
    physical_hash: str
    row_count: int | None = None
    column_count: int | None = None
    summary_preview: dict[str, Any] | None = None


class ColumnInfo(BaseModel):
    name: str
    dtype: str


class ArtifactPreviewResponse(BaseModel):
    artifact_id: str
    media_type: str
    row_count: int | None = None
    column_count: int | None = None
    columns: list[ColumnInfo] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    json_content: dict[str, Any] | None = None
    limit: int = 100
    offset: int = 0


# ---------------------------------------------------------------------------
# Manual Binning Editor (Phase 3E)
# ---------------------------------------------------------------------------

class ManualBinningSourceInfo(BaseModel):
    fine_classing_step_id: str
    fine_classing_artifact_id: str
    variable_selection_step_id: str
    variable_selection_artifact_id: str


class ManualBinningEditorStateResponse(BaseModel):
    plan_id: str
    plan_version_id: str
    step_id: str = "manual-binning"
    ready: bool = False
    blocked_reason: str | None = None
    required_steps: list[str] = Field(default_factory=list)
    source: ManualBinningSourceInfo | None = None
    selected_variables: list[str] = Field(default_factory=list)
    source_bins_by_variable: dict[str, Any] = Field(default_factory=dict)
    current_overrides: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class ManualBinningPreviewRequest(BaseModel):
    project_id: str
    plan_version_id: str
    overrides: list[dict[str, Any]] = Field(default_factory=list)


class PreviewDiagnostics(BaseModel):
    override_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class ManualBinningPreviewResponse(BaseModel):
    valid: bool = False
    refined_bins_by_variable: dict[str, Any] = Field(default_factory=dict)
    diagnostics: PreviewDiagnostics | None = None


# ---------------------------------------------------------------------------
# Branches (Phase 4)
# ---------------------------------------------------------------------------

class BranchStepItem(BaseModel):
    step_id: str
    canonical_step_id: str
    branch_id: str | None = None
    is_shared_upstream: bool = False
    is_branch_owned: bool = True


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
    steps: list[BranchStepItem] = Field(default_factory=list)
    is_champion: bool = False
    latest_run_id: str | None = None
    readiness: str = "not_run"
    warning_count: int = 0
    error_count: int = 0


class BranchListItem(BaseModel):
    branch_id: str
    plan_id: str
    name: str
    branch_type: str
    status: str = "active"
    base_branch_id: str | None = None
    base_plan_version_id: str
    head_plan_version_id: str
    branch_point_step_id: str | None = None
    branch_point_canonical_step_id: str | None = None
    is_champion: bool = False
    latest_run_id: str | None = None
    readiness: str = "not_run"
    warning_count: int = 0
    error_count: int = 0


class BranchListResponse(BaseModel):
    project_id: str
    branches: list[BranchListItem]


class MigrateRequest(BaseModel):
    project_id: str


class MigrateResponse(BaseModel):
    project_id: str
    branches_created: int
    plan_versions_mapped: int
    steps_mapped: int


# ---------------------------------------------------------------------------
# Branch Creation (Phase 4B)
# ---------------------------------------------------------------------------

class CreateBranchRequest(BaseModel):
    project_id: str
    base_plan_version_id: str
    base_branch_id: str | None = None
    branch_point_step_id: str
    name: str
    description: str | None = None
    branch_type: str
    created_reason: str
    segment_filter_spec: dict[str, Any] | None = None


class CreateBranchResponse(BaseModel):
    branch_id: str
    plan_id: str
    new_plan_version_id: str
    name: str
    branch_type: str
    branch_point_step_id: str | None = None
    branch_point_canonical_step_id: str | None = None
    created_step_ids: dict[str, str] = Field(default_factory=dict)
    shared_upstream_step_ids: list[str] = Field(default_factory=list)
    status: str = "not_run"
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Comparison (Phase 4D)
# ---------------------------------------------------------------------------

class CreateComparisonRequest(BaseModel):
    project_id: str
    plan_id: str
    baseline_branch_id: str
    challenger_branch_ids: list[str]
    comparison_spec: dict[str, Any] = Field(default_factory=lambda: {
        "roles": ["train", "test", "oot"],
        "include_woe_iv": True,
        "include_model": True,
        "include_validation": True,
        "include_cutoff": True,
        "include_warnings": True,
    })
    created_reason: str | None = None


class MissingStaleEvidence(BaseModel):
    branch_id: str
    canonical_step_id: str
    step_id: str
    status: str


class ComparisonResponse(BaseModel):
    comparison_id: str
    project_id: str
    plan_id: str
    baseline_branch_id: str
    challenger_branch_ids: list[str]
    latest_snapshot_id: str | None = None
    latest_ready: bool | None = None
    blocked_reason: str | None = None
    missing_or_stale: list[MissingStaleEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""


class RefreshComparisonResponse(BaseModel):
    comparison_id: str
    comparison_snapshot_id: str | None = None
    ready: bool = False
    comparison_artifact_id: str | None = None
    refreshed_at: str = ""
    blocked_reason: str | None = None
    missing_or_stale: list[MissingStaleEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ComparisonSnapshotResponse(BaseModel):
    comparison_snapshot_id: str
    comparison_id: str
    comparison_artifact_id: str
    ready: bool = False
    created_at: str = ""


# ---------------------------------------------------------------------------
# Champion (Phase 4E)
# ---------------------------------------------------------------------------

class AssignChampionRequest(BaseModel):
    project_id: str
    branch_id: str
    comparison_id: str
    comparison_snapshot_id: str
    scope_type: str = "project"
    scope_key: str = "default"
    assigned_reason: str


class ChampionResponse(BaseModel):
    champion_assignment_id: str
    plan_id: str
    champion_branch_id: str
    previous_champion_branch_id: str | None = None
    scope_type: str
    scope_key: str
    assigned_at: str = ""
    assigned_reason: str = ""


# ---------------------------------------------------------------------------
# Export (Phase 4E)
# ---------------------------------------------------------------------------

class ExportAuditPackRequest(BaseModel):
    project_id: str
    plan_id: str
    branch_id: str
    comparison_id: str | None = None
    comparison_snapshot_id: str | None = None
    include_row_level_data: bool = False
    include_report: bool = False
    report_mode: str = "branch"
    export_path: str | None = None


class ExportDiagnostic(BaseModel):
    code: str
    message: str


class ExportAuditPackResponse(BaseModel):
    export_path: str
    export_id: str
    file_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    diagnostics: list[ExportDiagnostic] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 5 — Reports
# ---------------------------------------------------------------------------

class ReportReadinessRequest(BaseModel):
    target_branch_id: str
    report_mode: str = "branch"
    include_challenger_comparison: bool = False


class ReadinessItem(BaseModel):
    code: str
    message: str


class ReportReadinessResponse(BaseModel):
    ready: bool = False
    status: str = ""
    blockers: list[ReadinessItem] = Field(default_factory=list)
    warnings: list[ReadinessItem] = Field(default_factory=list)


class GenerateReportRequest(BaseModel):
    target_branch_id: str
    report_mode: str = "branch"
    include_challenger_comparison: bool = False
    include_supporting_artifacts: bool = True
    output_formats: list[str] = Field(default_factory=lambda: ["json", "html"])
    export_zip: bool = False


class GenerateReportResponse(BaseModel):
    report_id: str
    status: str = ""
    report_bundle_path: str = ""
    html_path: str = ""
    export_path: str = ""
    zip_path: str = ""
    warnings: list[ReadinessItem] = Field(default_factory=list)


class ReportMetadataResponse(BaseModel):
    report_id: str
    created_at: str = ""
    target_branch_id: str = ""
    report_mode: str = ""
    html_path: str = ""
    bundle_path: str = ""
    export_path: str = ""
    zip_path: str = ""
    status: str = ""


# ---------------------------------------------------------------------------
# Node Types (Phase 6)
# ---------------------------------------------------------------------------

class NodeTypeItem(BaseModel):
    node_type: str
    version: str
    category: str
    description: str = ""
    model_family: str | None = None
    feature_strategies: list[str] = Field(default_factory=list)
    interpretability_level: str | None = None
    champion_eligibility: str | None = None
    optional_dependencies: list[str] = Field(default_factory=list)
    input_roles: list[str] = Field(default_factory=list)
    output_roles: list[str] = Field(default_factory=list)


class NodeTypeListResponse(BaseModel):
    node_types: list[NodeTypeItem]
    count: int


class NodeTypeSchemaResponse(BaseModel):
    node_type: str
    version: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


# ---------------------------------------------------------------------------
# Method Summary (Phase 6)
# ---------------------------------------------------------------------------

class MethodSummaryResponse(BaseModel):
    branch_id: str
    model_family: str | None = None
    feature_strategy: str | None = None
    feature_count: int = 0
    interpretability_level: str | None = None
    champion_eligibility: str | None = None
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_readiness: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Model Ranking (Phase 6)
# ---------------------------------------------------------------------------

class ModelRankingItem(BaseModel):
    branch_id: str
    branch_label: str = ""
    model_family: str | None = None
    rank: int = 0
    metric_name: str = ""
    metric_value: float | None = None
    interpretability_level: str | None = None
    champion_eligible: bool = False
    limitations_summary: list[str] = Field(default_factory=list)


class ModelRankingResponse(BaseModel):
    comparison_id: str
    metric_name: str
    rankings: list[ModelRankingItem]
    total_branches: int = 0
