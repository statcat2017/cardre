import type {
  ArtifactPreviewResponse,
  ArtifactResponse,
  ArtifactSummaryResponse,
  AssignChampionBody,
  BranchListResponse,
  BranchResponse,
  ChampionResponse,
  ComparisonResponse,
  ComparisonSnapshotResponse,
  CreateBranchBody,
  CreateBranchResponse,
  CreateProjectBody,
  ExportAuditPackBody,
  ExportAuditPackResponse,
  GenerateReportResponse,
  HealthResponse,
  ImportBody,
  ManualBinningEditorStateResponse,
  ManualBinningPreviewBody,
  ManualBinningPreviewResponse,
  MethodSummaryResponse,
  MigrateResponse,
  ModelRankingResponse,
  NodeTypeListResponse,
  NodeTypeSchemaResponse,
  PlanResponse,
  ProjectArtifactsResponse,
  ProjectDetailResponse,
  ProjectPlansResponse,
  ProjectResponse,
  ProjectRunsResponse,
  RefreshComparisonResponse,
  ReportReadinessResponse,
  RunBody,
  RunResponse,
  RunStepsResponse,
  UpdateStepParamsBody,
  UpdateStepParamsResponse,
} from "../types";

export function getBaseUrl(): string {
  return (window as unknown as Record<string, string>).__API_URL__ || "http://127.0.0.1:8752";
}

class ApiError extends Error {
  status: number;
  detail: { code: string; message: string };

  constructor(status: number, body: { detail?: { code: string; message: string } }) {
    super(body.detail?.message || `HTTP ${status}`);
    this.status = status;
    this.detail = body.detail || { code: "UNKNOWN", message: `HTTP ${status}` };
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw new ApiError(res.status, await res.json());
  return res.json();
}

export const api = {
  health: () => fetchJson<HealthResponse>("/health"),

  createProject: (body: CreateProjectBody) =>
    fetchJson<ProjectResponse>("/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getProject: (id: string) => fetchJson<ProjectDetailResponse>(`/projects/${id}`),

  getProjectPlans: (id: string) => fetchJson<ProjectPlansResponse>(`/projects/${id}/plans`),

  importDataset: (body: ImportBody) =>
    fetchJson<ArtifactResponse>("/datasets/import", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getPlan: (id: string, projectId?: string) => {
    const qs = projectId ? `?project_id=${projectId}` : "";
    return fetchJson<PlanResponse>(`/plans/${id}${qs}`);
  },

  updateStepParams: (planId: string, stepId: string, body: UpdateStepParamsBody) =>
    fetchJson<UpdateStepParamsResponse>(`/plans/${planId}/steps/${stepId}/params`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getProjectRuns: (projectId: string) =>
    fetchJson<ProjectRunsResponse>(`/projects/${projectId}/runs`),

  getProjectArtifacts: (projectId: string, params?: { role?: string; artifact_type?: string; producing_step_id?: string; run_id?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.role) qs.set("role", params.role);
    if (params?.artifact_type) qs.set("artifact_type", params.artifact_type);
    if (params?.producing_step_id) qs.set("producing_step_id", params.producing_step_id);
    if (params?.run_id) qs.set("run_id", params.run_id);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    const query = qs.toString();
    return fetchJson<ProjectArtifactsResponse>(`/projects/${projectId}/artifacts${query ? `?${query}` : ""}`);
  },

  runPlan: (body: RunBody) =>
    fetchJson<RunResponse>("/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getRun: (id: string) => fetchJson<RunResponse>(`/runs/${id}`),

  getRunSteps: (id: string) => fetchJson<RunStepsResponse>(`/runs/${id}/steps`),

  getArtifact: (id: string) => fetchJson<ArtifactResponse>(`/artifacts/${id}`),

  getArtifactSummary: (id: string) =>
    fetchJson<ArtifactSummaryResponse>(`/artifacts/${id}/summary`),

  getArtifactPreview: (id: string, limit = 100, offset = 0) =>
    fetchJson<ArtifactPreviewResponse>(`/artifacts/${id}/preview?limit=${limit}&offset=${offset}`),

  // stepId defaults to "manual-binning" for the baseline step; branch-owned steps
  // use IDs like "manual-binning__br_xxx" — pass the actual step_id from plan data.
  getManualBinningEditorState: (planId: string, projectId: string, stepId = "manual-binning") =>
    fetchJson<ManualBinningEditorStateResponse>(`/plans/${planId}/steps/${stepId}/editor-state?project_id=${projectId}`),

  previewManualBinning: (planId: string, body: ManualBinningPreviewBody, stepId = "manual-binning") =>
    fetchJson<ManualBinningPreviewResponse>(`/plans/${planId}/steps/${stepId}/manual-binning/preview`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Phase 4 — Branches
  listBranches: (projectId: string, params?: { plan_id?: string; branch_type?: string; status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.plan_id) qs.set("plan_id", params.plan_id);
    if (params?.branch_type) qs.set("branch_type", params.branch_type);
    if (params?.status) qs.set("status", params.status);
    const query = qs.toString();
    return fetchJson<BranchListResponse>(`/projects/${projectId}/branches${query ? `?${query}` : ""}`);
  },

  getBranch: (branchId: string, projectId?: string) => {
    const qs = projectId ? `?project_id=${projectId}` : "";
    return fetchJson<BranchResponse>(`/branches/${branchId}${qs}`);
  },

  createBranch: (planId: string, body: CreateBranchBody) =>
    fetchJson<CreateBranchResponse>(`/plans/${planId}/branches`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  migrateBaseline: (projectId: string) =>
    fetchJson<MigrateResponse>("/migrations/baseline", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
    }),

  // Phase 4 — Comparisons
  createComparison: (body: { project_id: string; plan_id: string; baseline_branch_id: string; challenger_branch_ids: string[]; comparison_spec?: Record<string, unknown>; created_reason?: string }) =>
    fetchJson<ComparisonResponse>("/branch-comparisons", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getComparison: (id: string) => fetchJson<ComparisonResponse>(`/branch-comparisons/${id}`),

  refreshComparison: (id: string) =>
    fetchJson<RefreshComparisonResponse>(`/branch-comparisons/${id}/refresh`, {
      method: "POST",
    }),

  getComparisonSnapshot: (id: string) =>
    fetchJson<ComparisonSnapshotResponse>(`/branch-comparison-snapshots/${id}`),

  // Phase 4 — Champion
  assignChampion: (planId: string, body: AssignChampionBody) =>
    fetchJson<ChampionResponse>(`/plans/${planId}/champion`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getChampion: (planId: string, projectId: string) =>
    fetchJson<ChampionResponse>(`/plans/${planId}/champion?project_id=${projectId}`),

  // Phase 4 — Export
  exportAuditPack: (body: ExportAuditPackBody) =>
    fetchJson<ExportAuditPackResponse>("/exports/audit-pack", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Phase 5 — Reports
  getReportReadiness: (projectId: string, runId: string, body: { target_branch_id: string; report_mode?: string; include_challenger_comparison?: boolean }) =>
    fetchJson<ReportReadinessResponse>(`/projects/${projectId}/runs/${runId}/report-readiness`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  generateReport: (projectId: string, runId: string, body: { target_branch_id: string; report_mode?: string; include_challenger_comparison?: boolean; include_supporting_artifacts?: boolean; output_formats?: string[]; export_zip?: boolean }) =>
    fetchJson<GenerateReportResponse>(`/projects/${projectId}/runs/${runId}/reports`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getReportMetadata: (projectId: string, runId: string, reportId: string) =>
    fetchJson<{ report_id: string; created_at: string; target_branch_id: string; report_mode: string; html_path: string; bundle_path: string; export_path: string; status: string }>(
      `/projects/${projectId}/runs/${runId}/reports/${reportId}`,
    ),

  listNodeTypes: () => fetchJson<NodeTypeListResponse>("/node-types"),

  getNodeTypeSchema: (nodeType: string) =>
    fetchJson<NodeTypeSchemaResponse>(`/node-types/${encodeURIComponent(nodeType)}/schema`),

  getBranchMethodSummary: (branchId: string, projectId: string) =>
    fetchJson<MethodSummaryResponse>(`/branches/${branchId}/method-summary?project_id=${projectId}`),

  getModelRanking: (snapshotId: string, projectId: string, metric?: string) => {
    const qs = new URLSearchParams({ project_id: projectId });
    if (metric) qs.set("metric", metric);
    return fetchJson<ModelRankingResponse>(`/branch-comparison-snapshots/${snapshotId}/model-ranking?${qs.toString()}`);
  },
};

export function getReportServeUrl(projectId: string, htmlPath: string): string {
  return `${getBaseUrl()}/projects/${projectId}/reports/serve?path=${encodeURIComponent(htmlPath)}`;
}
