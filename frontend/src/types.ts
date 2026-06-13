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
}

export interface RunResponse {
  run_id: string;
  plan_version_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  step_count: number;
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
  warnings: string[];
  errors: string[];
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
