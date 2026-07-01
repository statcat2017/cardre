/**
 * TypeScript types matching the Cardre v2 full API surface.
 * Phase 4 — generated manually to match Pydantic models in cardre/api/schemas.py.
 *
 * No frontend/src/types.ts — use generated components types only.
 */

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

export interface ProjectCreateRequest {
  name: string;
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

export interface PlanListResponse {
  plans: PlanResponse[];
}

export interface PlanCreateRequest {
  name: string;
}

export interface PlanVersionResponse {
  plan_version_id: string;
  plan_id: string;
  version_number: number;
  is_committed: boolean;
  created_at: string;
  description: string;
}

export interface PlanVersionListResponse {
  versions: PlanVersionResponse[];
}

export interface PlanVersionUpdate {
  description?: string;
}

export interface PlanStepResponse {
  step_id: string;
  plan_version_id: string;
  node_type: string;
  node_version: string;
  category: string;
  params: Record<string, unknown>;
  params_hash: string;
  parent_step_ids: string[];
  branch_label: string;
  position: number;
  canonical_step_id: string;
  branch_id: string | null;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export interface RunResponse {
  run_id: string;
  plan_version_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  step_count: number;
  branch_id: string | null;
  executed_step_ids: string[];
  diagnostics: Record<string, unknown>[];
  latest_error: Record<string, unknown> | null;
  heartbeat_at: string | null;
  is_stale: boolean;
}

export interface RunListResponse {
  runs: RunResponse[];
}

export interface RunCreateRequest {
  plan_version_id: string;
  force?: boolean;
  sync?: boolean;
}

export interface RunStepResponse {
  run_step_id: string;
  run_id: string;
  step_id: string;
  plan_version_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  execution_fingerprint: Record<string, unknown>;
  warnings: Record<string, unknown>[];
  errors: Record<string, unknown>[];
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

export interface EvidenceEdgeResponse {
  evidence_edge_id: string;
  run_id: string;
  run_step_id: string;
  plan_version_id: string;
  step_id: string;
  parent_step_id: string;
  source_run_id: string;
  source_run_step_id: string;
  policy: string;
  source_label: string;
  is_reused: boolean;
  is_stale: boolean;
  stale_reason: string | null;
  created_at: string;
}

export interface EvidenceArtifactResponse {
  evidence_artifact_id: string;
  evidence_edge_id: string;
  artifact_id: string;
  role: string;
  created_at: string;
}

export interface ResolvedEvidenceResponse {
  run_step_id: string;
  edges: EvidenceEdgeResponse[];
  artifacts: EvidenceArtifactResponse[];
}

export interface StalenessExplanationResponse {
  step_id: string;
  status: "fresh" | "stale" | "missing";
  upstream_changes: Record<string, boolean>;
  missing_evidence: string[];
}

// ---------------------------------------------------------------------------
// Artifacts
// ---------------------------------------------------------------------------

export interface ArtifactResponse {
  artifact_id: string;
  artifact_type: string;
  role: string;
  path: string;
  physical_hash: string;
  logical_hash: string;
  media_type: string;
  created_at: string;
}

export interface ArtifactListResponse {
  artifacts: ArtifactResponse[];
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
// Branches (governance-gated)
// ---------------------------------------------------------------------------

export interface BranchResponse {
  branch_id: string;
  project_id: string;
  plan_id: string;
  name: string;
  description: string | null;
  branch_type: string;
  status: string;
  base_branch_id: string | null;
  base_plan_version_id: string;
  head_plan_version_id: string;
  branch_point_step_id: string | null;
  branch_point_canonical_step_id: string | null;
  created_reason: string;
  created_at: string;
  updated_at: string;
}

export interface BranchListResponse {
  branches: BranchResponse[];
}

export interface BranchCreateRequest {
  plan_id: string;
  name: string;
  branch_type: string;
  base_plan_version_id: string;
  head_plan_version_id: string;
  description?: string | null;
  base_branch_id?: string | null;
  branch_point_step_id?: string | null;
  created_reason?: string;
}

// ---------------------------------------------------------------------------
// Comparisons (governance-gated)
// ---------------------------------------------------------------------------

export interface ComparisonResponse {
  comparison_id: string;
  project_id: string;
  plan_id: string;
  baseline_branch_id: string;
  created_at: string;
  latest_ready: boolean | null;
}

export interface ComparisonListResponse {
  comparisons: ComparisonResponse[];
}

// ---------------------------------------------------------------------------
// Champion (governance-gated)
// ---------------------------------------------------------------------------

export interface ChampionAssignmentResponse {
  champion_assignment_id: string;
  project_id: string;
  plan_id: string;
  champion_branch_id: string;
  selected_plan_version_id: string;
  assigned_at: string;
  superseded_at: string | null;
}

export interface ChampionResponse {
  assignment: ChampionAssignmentResponse | null;
}

// ---------------------------------------------------------------------------
// Node types
// ---------------------------------------------------------------------------

export interface NodeTypeResponse {
  node_type: string;
  display_name: string;
  description: string;
  category: string;
  tier: string;
  has_params: boolean;
}

export interface NodeTypeListResponse {
  node_types: NodeTypeResponse[];
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export interface ExportResponse {
  export_id: string;
  run_id: string;
  export_type: string;
  path: string;
  created_at: string;
  size_bytes: number;
}

export interface ExportListResponse {
  exports: ExportResponse[];
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export interface ReportResponse {
  report_id: string;
  run_id: string | null;
  report_type: string;
  path: string;
  created_at: string;
}

export interface ReportListResponse {
  reports: ReportResponse[];
}

// ---------------------------------------------------------------------------
// Canonical error codes
// ---------------------------------------------------------------------------

export const ErrorCodes = {
  SIDECAR_UNREACHABLE: "SIDECAR_UNREACHABLE",
  REQUEST_TIMEOUT: "REQUEST_TIMEOUT",
  REQUEST_ABORTED: "REQUEST_ABORTED",
  EMPTY_OK_BODY: "EMPTY_OK_BODY",
  EMPTY_ERROR_RESPONSE: "EMPTY_ERROR_RESPONSE",
  MALFORMED_JSON_RESPONSE: "MALFORMED_JSON_RESPONSE",
  HTML_ERROR_RESPONSE: "HTML_ERROR_RESPONSE",
  NON_JSON_ERROR_RESPONSE: "NON_JSON_ERROR_RESPONSE",
  GOVERNANCE_DISABLED: "GOVERNANCE_DISABLED",
  PROJECT_NOT_FOUND: "PROJECT_NOT_FOUND",
  PLAN_NOT_FOUND: "PLAN_NOT_FOUND",
  PLAN_VERSION_NOT_FOUND: "PLAN_VERSION_NOT_FOUND",
  PLAN_VERSION_IMMUTABLE: "PLAN_VERSION_IMMUTABLE",
  RUN_NOT_FOUND: "RUN_NOT_FOUND",
  STEP_NOT_FOUND: "STEP_NOT_FOUND",
  ARTIFACT_NOT_FOUND: "ARTIFACT_NOT_FOUND",
  BRANCH_NOT_FOUND: "BRANCH_NOT_FOUND",
} as const;
