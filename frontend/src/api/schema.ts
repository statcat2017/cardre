/**
 * TypeScript types matching the Cardre v2 minimal API schemas.
 * Phase 2 — generated manually to match Pydantic models in cardre/api/schemas.py.
 */

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  version: string;
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export interface ProjectResponse {
  project_id: string;
  name: string;
  created_at: string;
  cardre_version: string;
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
}

// ---------------------------------------------------------------------------
// Plans
// ---------------------------------------------------------------------------

export interface PlanResponse {
  plan_id: string;
  project_id: string;
  name: string;
  created_at: string;
}

export interface PlanVersionResponse {
  plan_version_id: string;
  plan_id: string;
  version_number: number;
  is_committed: boolean;
  created_at: string;
  description: string;
}

// ---------------------------------------------------------------------------
// Manual Binning
// ---------------------------------------------------------------------------

export interface ManualBinningReviewResponse {
  review_id: string;
  plan_version_id: string;
  step_id: string;
  status: string;
  reviewer_notes: string;
  affected_downstream_step_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ManualBinningReviewUpdate {
  status?: string;
  reviewer_notes?: string;
}

export interface ManualBinningEditRequest {
  plan_version_id: string;
  step_id: string;
  overrides: Record<string, unknown>[];
  reviewer_notes: string;
  status: string;
  affected_downstream_step_ids: string[];
}

export interface ManualBinningEditResponse {
  new_plan_version_id: string;
  review_id: string;
  affected_step_ids: string[];
}

export interface ManualBinningPreviewRequest {
  variable_data: Record<string, unknown>;
}

export interface ManualBinningPreviewResponse {
  woe_by_bin: Record<string, unknown>[];
  iv: number;
  event_rate_by_bin: Record<string, unknown>[];
}

// ---------------------------------------------------------------------------
// Error envelope
// ---------------------------------------------------------------------------

export interface ErrorDetail {
  code: string;
  message: string;
  context: Record<string, unknown>;
}

export interface ErrorResponse {
  detail: ErrorDetail;
}
