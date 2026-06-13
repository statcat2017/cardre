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
    dataset_id: str = "uci-statlog-german-credit"


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


class RunResponse(BaseModel):
    run_id: str
    plan_version_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    step_count: int = 0


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

class ArtifactListItem(BaseModel):
    artifact_id: str
    artifact_type: str
    role: str
    path: str
    physical_hash: str
    logical_hash: str
    media_type: str
    created_at: str
    metadata: dict[str, Any]


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
