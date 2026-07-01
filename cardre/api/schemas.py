"""Pydantic models for the Cardre v2 minimal API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectResponse(BaseModel):
    project_id: str
    name: str
    created_at: str
    cardre_version: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class PlanResponse(BaseModel):
    plan_id: str
    project_id: str
    name: str
    created_at: str


class PlanVersionResponse(BaseModel):
    plan_version_id: str
    plan_id: str
    version_number: int
    is_committed: bool
    created_at: str
    description: str = ""


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


__all__ = [
    "HealthResponse",
    "ProjectResponse",
    "ProjectListResponse",
    "PlanResponse",
    "PlanVersionResponse",
    "ManualBinningReviewResponse",
    "ManualBinningReviewUpdate",
    "ManualBinningEditRequest",
    "ManualBinningEditResponse",
    "ManualBinningPreviewRequest",
    "ManualBinningPreviewResponse",
]
