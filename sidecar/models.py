"""Pydantic request/response models for the Cardre sidecar API."""

from __future__ import annotations

from datetime import datetime
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
