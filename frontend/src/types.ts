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
}

export type StepStatusCode =
  | "not_run"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

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
