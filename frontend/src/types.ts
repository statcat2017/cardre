// Type generation: run python3 scripts/generate-openapi-types.py to regenerate from OpenAPI schema

export interface HealthResponse {
  status: string;
  cardre_version: string;
}

export interface ProjectResponse {
  project_id: string;
  path: string;
  name: string;
  created_at: string;
}

export interface ProjectDetailResponse extends ProjectResponse {
  plan_count: number;
  run_count: number;
}

export interface CreateProjectBody {
  path: string;
  name: string;
}

export interface StepStatus {
  step_id: string;
  node_type: string;
  category: string;
  status: StepStatusCode;
  is_stale: boolean;
  position: number;
  params: Record<string, unknown>;
  canonical_step_id?: string;
  branch_id?: string | null;
}

export type StepStatusCode =
  | "not_run"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface PlanListItem {
  plan_id: string;
  name: string;
  latest_version_id: string;
  is_default: boolean;
  is_hidden: boolean;
}

export interface ProjectPlansResponse {
  project_id: string;
  plans: PlanListItem[];
}

export interface PlanResponse {
  plan_id: string;
  project_id: string;
  name: string;
  latest_version_id: string;
  steps: StepStatus[];
}

export interface RunBody {
  project_id: string;
  plan_version_id: string;
  run_scope?: string;
  branch_id?: string | null;
}

export interface RunResponse {
  run_id: string;
  plan_version_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  step_count: number;
  branch_id?: string | null;
  executed_step_ids?: string[];
}

export interface RunStepItem {
  run_step_id: string;
  step_id: string;
  node_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  input_artifact_ids: string[];
  output_artifact_ids: string[];
  warnings: Record<string, unknown>[];
  errors: Record<string, unknown>[];
  is_carried_forward: boolean;
}

export interface RunStepsResponse {
  run_id: string;
  steps: RunStepItem[];
}

export interface ArtifactResponse {
  artifact_id: string;
  artifact_type: string;
  role: string;
  path: string;
  physical_hash: string;
  logical_hash: string;
  media_type: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface ImportBody {
  project_id: string;
  source_path: string;
  dataset_id: string;
}

export interface UpdateStepParamsBody {
  project_id: string;
  base_plan_version_id: string;
  params: Record<string, unknown>;
}

export interface UpdateStepParamsResponse {
  plan_id: string;
  new_plan_version_id: string;
  changed_step_id: string;
  stale_step_ids: string[];
}

export interface RunListItem {
  run_id: string;
  plan_version_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  step_count: number;
}

export interface ProjectRunsResponse {
  project_id: string;
  runs: RunListItem[];
}

export interface ArtifactListItem {
  artifact_id: string;
  artifact_type: string;
  role: string;
  path: string;
  physical_hash: string;
  logical_hash: string;
  media_type: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface ProjectArtifactsResponse {
  project_id: string;
  artifacts: ArtifactListItem[];
}

export interface ArtifactSummaryResponse {
  artifact_id: string;
  artifact_type: string;
  role: string;
  media_type: string;
  logical_hash: string;
  physical_hash: string;
  row_count: number | null;
  column_count: number | null;
  summary_preview: Record<string, unknown> | null;
}

export interface ColumnInfo {
  name: string;
  dtype: string;
}

export interface ArtifactPreviewResponse {
  artifact_id: string;
  media_type: string;
  row_count: number | null;
  column_count: number | null;
  columns: ColumnInfo[];
  rows: Record<string, unknown>[];
  json_content: Record<string, unknown> | null;
  limit: number;
  offset: number;
}

export interface ManualBinningSourceInfo {
  fine_classing_step_id: string;
  fine_classing_artifact_id: string;
  variable_selection_step_id: string;
  variable_selection_artifact_id: string;
}

export interface ManualBinningEditorStateResponse {
  plan_id: string;
  plan_version_id: string;
  step_id: string;
  ready: boolean;
  blocked_reason: string | null;
  required_steps: string[];
  source: ManualBinningSourceInfo | null;
  selected_variables: string[];
  source_bins_by_variable: Record<string, unknown>;
  current_overrides: Record<string, unknown>[];
  warnings: Record<string, unknown>[];
}

export interface ManualBinningPreviewBody {
  project_id: string;
  plan_version_id: string;
  overrides: Record<string, unknown>[];
}

export interface PreviewDiagnostics {
  override_count: number;
  warnings: string[];
}

export interface ManualBinningPreviewResponse {
  valid: boolean;
  refined_bins_by_variable: Record<string, unknown>;
  diagnostics: PreviewDiagnostics | null;
}

export interface BranchStepItem {
  step_id: string;
  canonical_step_id: string;
  branch_id?: string | null;
  is_shared_upstream: boolean;
  is_branch_owned: boolean;
}

export interface BranchResponse {
  branch_id: string;
  project_id: string;
  plan_id: string;
  name: string;
  description?: string | null;
  branch_type: string;
  status: string;
  base_branch_id?: string | null;
  base_plan_version_id: string;
  head_plan_version_id: string;
  branch_point_step_id?: string | null;
  branch_point_canonical_step_id?: string | null;
  created_reason: string;
  steps: BranchStepItem[];
  is_champion?: boolean;
  latest_run_id?: string | null;
  readiness?: string;
  warning_count?: number;
  error_count?: number;
}

export interface BranchListItem {
  branch_id: string;
  plan_id: string;
  name: string;
  branch_type: string;
  status: string;
  base_branch_id?: string | null;
  base_plan_version_id: string;
  head_plan_version_id: string;
  branch_point_step_id?: string | null;
  branch_point_canonical_step_id?: string | null;
  is_champion?: boolean;
  latest_run_id?: string | null;
  readiness?: string;
  warning_count?: number;
  error_count?: number;
}

export interface BranchListResponse {
  project_id: string;
  branches: BranchListItem[];
}

export interface MigrateResponse {
  project_id: string;
  branches_created: number;
  plan_versions_mapped: number;
  steps_mapped: number;
}

export interface CreateBranchBody {
  project_id: string;
  base_plan_version_id: string;
  base_branch_id?: string | null;
  branch_point_step_id: string;
  name: string;
  description?: string | null;
  branch_type: string;
  created_reason: string;
  segment_filter_spec?: Record<string, unknown> | null;
}

export interface CreateBranchResponse {
  branch_id: string;
  plan_id: string;
  new_plan_version_id: string;
  name: string;
  branch_type: string;
  branch_point_step_id?: string | null;
  branch_point_canonical_step_id?: string | null;
  created_step_ids: Record<string, string>;
  shared_upstream_step_ids: string[];
  status: string;
  warnings: string[];
}

export interface ComparisonResponse {
  comparison_id: string;
  project_id: string;
  plan_id: string;
  baseline_branch_id: string;
  challenger_branch_ids: string[];
  latest_snapshot_id?: string | null;
  latest_ready?: boolean | null;
  blocked_reason?: string | null;
  missing_or_stale?: { branch_id: string; canonical_step_id: string; step_id: string; status: string }[];
  warnings?: string[];
  created_at?: string;
}

export interface RefreshComparisonResponse {
  comparison_id: string;
  comparison_snapshot_id?: string | null;
  ready: boolean;
  comparison_artifact_id?: string | null;
  refreshed_at?: string;
  blocked_reason?: string | null;
  missing_or_stale?: { branch_id: string; canonical_step_id: string; step_id: string; status: string }[];
  warnings?: string[];
}

export interface ComparisonSnapshotResponse {
  comparison_snapshot_id: string;
  comparison_id: string;
  comparison_artifact_id: string;
  ready: boolean;
  created_at?: string;
}

export interface AssignChampionBody {
  project_id: string;
  branch_id: string;
  comparison_id: string;
  comparison_snapshot_id: string;
  scope_type?: string;
  scope_key?: string;
  assigned_reason: string;
}

export interface ChampionResponse {
  champion_assignment_id: string;
  plan_id: string;
  champion_branch_id: string;
  previous_champion_branch_id?: string | null;
  scope_type: string;
  scope_key: string;
  assigned_at?: string;
  assigned_reason?: string;
}

export interface ExportAuditPackBody {
  project_id: string;
  plan_id: string;
  branch_id: string;
  comparison_id?: string | null;
  comparison_snapshot_id?: string | null;
  include_row_level_data?: boolean;
  include_report?: boolean;
  report_mode?: string;
  export_path?: string | null;
}

export interface ExportAuditPackResponse {
  export_path: string;
  export_id: string;
  file_count: number;
  warnings?: string[];
  diagnostics?: { code: string; message: string }[];
}

// Phase 5 — Reports
export interface ReportReadinessItem {
  code: string;
  message: string;
}

export interface ReportReadinessResponse {
  ready: boolean;
  status: string;
  blockers: ReportReadinessItem[];
  warnings: ReportReadinessItem[];
}

export interface GenerateReportResponse {
  report_id: string;
  status: string;
  report_bundle_path: string;
  html_path: string;
  export_path: string;
  zip_path: string;
  warnings: ReportReadinessItem[];
}
