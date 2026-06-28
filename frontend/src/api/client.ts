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
  ManualBinningReviewResponse,
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
  RunStepEvidenceResponse,
  RunStepsResponse,
  UpdateStepParamsBody,
  UpdateStepParamsResponse,
  WorkflowGuidance,
} from "../types";
import type { components } from "./schema";

export function getBaseUrl(): string {
  return (window as unknown as Record<string, string>).__API_URL__ || "http://127.0.0.1:8752";
}

export interface FetchOptions extends RequestInit {
  timeoutMs?: number;
  signal?: AbortSignal;
  allowEmpty?: boolean;
}

export const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: {
    code: string;
    message: string;
    recoverable?: boolean;
    severity?: string;
    context?: Record<string, unknown>;
    diagnostics?: Array<{ code: string; message: string; source?: string }>;
    request_id?: string;
    error_id?: string;
  };
  readonly requestId?: string;
  readonly rawBodyPreview?: string;
  readonly timedOutAtMs?: number;

  constructor(
    status: number,
    detail: ApiError["detail"],
    opts?: { requestId?: string; rawBodyPreview?: string; timedOutAtMs?: number },
  ) {
    super(detail.message || `HTTP ${status}`);
    this.status = status;
    this.code = detail.code;
    this.detail = detail;
    this.requestId = opts?.requestId;
    this.rawBodyPreview = opts?.rawBodyPreview;
    this.timedOutAtMs = opts?.timedOutAtMs;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

export function formatApiError(e: unknown): string {
  if (isApiError(e)) {
    const parts = [e.code];
    if (e.requestId) parts.push(`req=${e.requestId.slice(0, 8)}`);
    if (e.timedOutAtMs) parts.push(`timeout=${e.timedOutAtMs}ms`);
    return `${parts.join(" ")}: ${e.message}`;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}

export async function fetchJson<T>(path: string, init?: FetchOptions): Promise<T> {
  const url = `${getBaseUrl()}${path}`;
  const timeoutMs = init?.timeoutMs ?? 30_000;
  const allowEmpty = init?.allowEmpty ?? false;

  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  let didTimeout = false;

  if (init?.signal) {
    if (init.signal.aborted) {
      controller.abort();
    } else {
      init.signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  if (timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      didTimeout = true;
      controller.abort(new Error(`Request timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  }

  // Generate and send outbound request ID for diagnostics
  const outboundRequestId =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const mergedHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Cardre-Request-Id": outboundRequestId,
    ...(init?.headers as Record<string, string> | undefined),
  };

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: mergedHeaders,
    });
  } catch (e) {
    clearTimeout(timeoutId);
    if (didTimeout) {
      throw new ApiError(
        0,
        {
          code: "REQUEST_TIMEOUT",
          message: `Request timed out after ${timeoutMs}ms.`,
        },
        { timedOutAtMs: timeoutMs, requestId: outboundRequestId },
      );
    }
    if (controller.signal.aborted) {
      throw new ApiError(
        0,
        {
          code: "REQUEST_ABORTED",
          message: "Request was cancelled.",
        },
        { requestId: outboundRequestId },
      );
    }
    throw new ApiError(
      0,
      {
        code: "SIDECAR_UNREACHABLE",
        message: "Could not reach the Cardre sidecar.",
      },
      { rawBodyPreview: String(e), requestId: outboundRequestId },
    );
  }

  // Keep timeout active through body read — body streaming can also hang
  let text: string;
  try {
    text = await res.text();
  } catch (e) {
    clearTimeout(timeoutId);
    if (didTimeout) {
      throw new ApiError(
        0,
        {
          code: "REQUEST_TIMEOUT",
          message: `Response body timed out after ${timeoutMs}ms.`,
        },
        { timedOutAtMs: timeoutMs, requestId: outboundRequestId },
      );
    }
    throw new ApiError(
      0,
      {
        code: "SIDECAR_UNREACHABLE",
        message: "Could not read response body.",
      },
      { rawBodyPreview: String(e), requestId: outboundRequestId },
    );
  }
  clearTimeout(timeoutId);

  const requestId = res.headers.get("X-Cardre-Request-Id") ?? outboundRequestId;
  if (!res.ok) {
    if (text.length === 0) {
      throw new ApiError(
        res.status,
        {
          code: "EMPTY_ERROR_RESPONSE",
          message: `HTTP ${res.status} with empty body.`,
        },
        { requestId, rawBodyPreview: "" },
      );
    }
    let detail: ApiError["detail"] | undefined;
    try {
      const parsed = JSON.parse(text);
      detail = parsed?.detail;
    } catch {
      /* not JSON */
    }
    if (!detail || typeof detail.code !== "string" || typeof detail.message !== "string") {
      const preview = text.slice(0, 500);
      const code = text.trimStart().startsWith("<")
        ? "HTML_ERROR_RESPONSE"
        : "NON_JSON_ERROR_RESPONSE";
      throw new ApiError(
        res.status,
        {
          code,
          message: `HTTP ${res.status} returned a non-JSON body.`,
        },
        { requestId, rawBodyPreview: preview },
      );
    }
    throw new ApiError(res.status, detail, { requestId });
  }
  if (text.length === 0) {
    if (allowEmpty) return undefined as unknown as T;
    throw new ApiError(
      res.status,
      {
        code: "EMPTY_OK_BODY",
        message: "OK response was empty (expected JSON).",
      },
      { requestId, rawBodyPreview: "" },
    );
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(
      res.status,
      {
        code: "MALFORMED_JSON_RESPONSE",
        message: "OK response was not valid JSON.",
      },
      { requestId, rawBodyPreview: text.slice(0, 500) },
    );
  }
}

export const api = {
  health: () => fetchJson<HealthResponse>("/health", { timeoutMs: 5_000 }),

  createProject: (body: CreateProjectBody) =>
    fetchJson<ProjectResponse>("/projects", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 10_000,
    }),

  getProject: (id: string) =>
    fetchJson<ProjectDetailResponse>(`/projects/${id}`, { timeoutMs: 5_000 }),

  getProjectPlans: (id: string) =>
    fetchJson<ProjectPlansResponse>(`/projects/${id}/plans`, { timeoutMs: 5_000 }),

  importDataset: (body: ImportBody) =>
    fetchJson<ArtifactResponse>("/datasets/import", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 30_000,
    }),

  getPlan: (id: string, projectId?: string) => {
    const qs = projectId ? `?project_id=${projectId}` : "";
    return fetchJson<PlanResponse>(`/plans/${id}${qs}`, { timeoutMs: 5_000 });
  },

  getWorkflowGuidance: (
    planId: string,
    params?: { project_id?: string; branch_id?: string; run_id?: string },
  ) => {
    const qs = new URLSearchParams();
    if (params?.project_id) qs.set("project_id", params.project_id);
    if (params?.branch_id) qs.set("branch_id", params.branch_id);
    if (params?.run_id) qs.set("run_id", params.run_id);
    const query = qs.toString();
    return fetchJson<WorkflowGuidance>(
      `/plans/${planId}/workflow-guidance${query ? `?${query}` : ""}`,
      { timeoutMs: 5_000 },
    );
  },

  updateStepParams: (planId: string, stepId: string, body: UpdateStepParamsBody) =>
    fetchJson<UpdateStepParamsResponse>(`/plans/${planId}/steps/${stepId}/params`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 10_000,
    }),

  getProjectRuns: (projectId: string) =>
    fetchJson<ProjectRunsResponse>(`/projects/${projectId}/runs`, { timeoutMs: 5_000 }),

  getProjectArtifacts: (
    projectId: string,
    params?: {
      role?: string;
      artifact_type?: string;
      producing_step_id?: string;
      run_id?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const qs = new URLSearchParams();
    if (params?.role) qs.set("role", params.role);
    if (params?.artifact_type) qs.set("artifact_type", params.artifact_type);
    if (params?.producing_step_id) qs.set("producing_step_id", params.producing_step_id);
    if (params?.run_id) qs.set("run_id", params.run_id);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    const query = qs.toString();
    return fetchJson<ProjectArtifactsResponse>(
      `/projects/${projectId}/artifacts${query ? `?${query}` : ""}`,
      { timeoutMs: 10_000 },
    );
  },

  runPlan: (body: RunBody) =>
    fetchJson<RunResponse>("/runs", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 10_000,
    }),

  getProjectRun: (projectId: string, runId: string, opts?: FetchOptions) =>
    fetchJson<RunResponse>(`/runs/project/${projectId}/runs/${runId}`, {
      timeoutMs: 5_000,
      ...opts,
    }),

  getProjectRunSteps: (projectId: string, runId: string, opts?: FetchOptions) =>
    fetchJson<RunStepsResponse>(`/runs/project/${projectId}/runs/${runId}/steps`, {
      timeoutMs: 5_000,
      ...opts,
    }),

  getProjectArtifact: (projectId: string, artifactId: string) =>
    fetchJson<ArtifactResponse>(`/artifacts/project/${projectId}/artifacts/${artifactId}`, {
      timeoutMs: 5_000,
    }),

  getProjectArtifactSummary: (projectId: string, artifactId: string) =>
    fetchJson<ArtifactSummaryResponse>(
      `/artifacts/project/${projectId}/artifacts/${artifactId}/summary`,
      { timeoutMs: 5_000 },
    ),

  getProjectArtifactPreview: (projectId: string, artifactId: string, limit = 100, offset = 0) =>
    fetchJson<ArtifactPreviewResponse>(
      `/artifacts/project/${projectId}/artifacts/${artifactId}/preview?limit=${limit}&offset=${offset}`,
      { timeoutMs: 10_000 },
    ),

  getManualBinningEditorState: (
    planId: string,
    projectId: string,
    stepId = "manual-binning",
    planVersionId?: string,
  ) => {
    let url = `/plans/${planId}/steps/${stepId}/editor-state?project_id=${projectId}`;
    if (planVersionId) url += `&plan_version_id=${planVersionId}`;
    return fetchJson<ManualBinningEditorStateResponse>(url, { timeoutMs: 5_000 });
  },

  previewManualBinning: (
    planId: string,
    body: ManualBinningPreviewBody,
    stepId = "manual-binning",
  ) =>
    fetchJson<ManualBinningPreviewResponse>(
      `/plans/${planId}/steps/${stepId}/manual-binning/preview`,
      {
        method: "POST",
        body: JSON.stringify(body),
        timeoutMs: 10_000,
      },
    ),

  reviewManualBinning: (
    planId: string,
    stepId: string,
    body: {
      project_id: string;
      plan_version_id: string;
      step_id: string;
      reviewed: boolean;
      accept_automated: boolean;
      overrides?: Record<string, unknown>[];
      reason_code?: string;
      review_reason?: string;
      reviewed_by?: string;
    },
  ) =>
    fetchJson<ManualBinningReviewResponse>(
      `/plans/${planId}/steps/${stepId}/manual-binning/review`,
      {
        method: "POST",
        body: JSON.stringify(body),
        timeoutMs: 10_000,
      },
    ),

  listBranches: (
    projectId: string,
    params?: { plan_id?: string; branch_type?: string; status?: string },
  ) => {
    const qs = new URLSearchParams();
    if (params?.plan_id) qs.set("plan_id", params.plan_id);
    if (params?.branch_type) qs.set("branch_type", params.branch_type);
    if (params?.status) qs.set("status", params.status);
    const query = qs.toString();
    return fetchJson<BranchListResponse>(
      `/projects/${projectId}/branches${query ? `?${query}` : ""}`,
      { timeoutMs: 5_000 },
    );
  },

  getBranch: (branchId: string, projectId?: string) => {
    const qs = projectId ? `?project_id=${projectId}` : "";
    return fetchJson<BranchResponse>(`/branches/${branchId}${qs}`, { timeoutMs: 5_000 });
  },

  createBranch: (planId: string, body: CreateBranchBody) =>
    fetchJson<CreateBranchResponse>(`/plans/${planId}/branches`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 10_000,
    }),

  migrateBaseline: (projectId: string) =>
    fetchJson<MigrateResponse>("/migrations/baseline", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId }),
      timeoutMs: 30_000,
    }),

  createComparison: (body: {
    project_id: string;
    plan_id: string;
    baseline_branch_id: string;
    challenger_branch_ids: string[];
    comparison_spec?: Record<string, unknown>;
    created_reason?: string;
  }) =>
    fetchJson<ComparisonResponse>("/branch-comparisons", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 10_000,
    }),

  getComparison: (id: string) =>
    fetchJson<ComparisonResponse>(`/branch-comparisons/${id}`, { timeoutMs: 5_000 }),

  refreshComparison: (id: string) =>
    fetchJson<RefreshComparisonResponse>(`/branch-comparisons/${id}/refresh`, {
      method: "POST",
      timeoutMs: 30_000,
    }),

  getComparisonSnapshot: (id: string) =>
    fetchJson<ComparisonSnapshotResponse>(`/branch-comparison-snapshots/${id}`, {
      timeoutMs: 5_000,
    }),

  assignChampion: (planId: string, body: AssignChampionBody) =>
    fetchJson<ChampionResponse>(`/plans/${planId}/champion`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 10_000,
    }),

  getChampion: (planId: string, projectId: string) =>
    fetchJson<ChampionResponse>(`/plans/${planId}/champion?project_id=${projectId}`, {
      timeoutMs: 5_000,
    }),

  exportAuditPack: (body: ExportAuditPackBody) =>
    fetchJson<ExportAuditPackResponse>("/exports/audit-pack", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 60_000,
    }),

  getReportReadiness: (
    projectId: string,
    runId: string,
    body: {
      target_branch_id: string;
      report_mode?: string;
      include_challenger_comparison?: boolean;
    },
  ) =>
    fetchJson<ReportReadinessResponse>(`/projects/${projectId}/runs/${runId}/report-readiness`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 10_000,
    }),

  generateReport: (
    projectId: string,
    runId: string,
    body: {
      target_branch_id: string;
      report_mode?: string;
      include_challenger_comparison?: boolean;
      include_supporting_artifacts?: boolean;
      output_formats?: string[];
      export_zip?: boolean;
    },
  ) =>
    fetchJson<GenerateReportResponse>(`/projects/${projectId}/runs/${runId}/reports`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 120_000,
    }),

  getReportMetadata: (projectId: string, runId: string, reportId: string) =>
    fetchJson<{
      report_id: string;
      created_at: string;
      target_branch_id: string;
      report_mode: string;
      html_path: string;
      bundle_path: string;
      export_path: string;
      status: string;
    }>(`/projects/${projectId}/runs/${runId}/reports/${reportId}`, { timeoutMs: 5_000 }),

  listNodeTypes: () => fetchJson<NodeTypeListResponse>("/node-types", { timeoutMs: 5_000 }),

  getNodeTypeSchema: (nodeType: string) =>
    fetchJson<NodeTypeSchemaResponse>(`/node-types/${encodeURIComponent(nodeType)}/schema`, {
      timeoutMs: 5_000,
    }),

  getBranchMethodSummary: (branchId: string, projectId: string) =>
    fetchJson<MethodSummaryResponse>(
      `/branches/${branchId}/method-summary?project_id=${projectId}`,
      { timeoutMs: 5_000 },
    ),

  getModelRanking: (snapshotId: string, projectId: string, metric?: string) => {
    const qs = new URLSearchParams({ project_id: projectId });
    if (metric) qs.set("metric", metric);
    return fetchJson<ModelRankingResponse>(
      `/branch-comparison-snapshots/${snapshotId}/model-ranking?${qs.toString()}`,
      { timeoutMs: 5_000 },
    );
  },

  listRunReports: (projectId: string, runId: string) =>
    fetchJson<components["schemas"]["ReportMetadataResponse"][]>(
      `/projects/${projectId}/runs/${runId}/reports`,
      { timeoutMs: 5_000 },
    ),

  getStepEvidence: (runId: string, stepId: string, projectId: string) =>
    fetchJson<RunStepEvidenceResponse>(
      `/runs/${runId}/steps/${stepId}/evidence?project_id=${projectId}`,
      { timeoutMs: 10_000 },
    ),

  getRunEvidence: (runId: string, projectId: string) =>
    fetchJson<RunStepEvidenceResponse>(`/runs/${runId}/evidence?project_id=${projectId}`, {
      timeoutMs: 10_000,
    }),
};

export function getReportServeUrl(projectId: string, htmlPath: string): string {
  return `${getBaseUrl()}/projects/${projectId}/reports/serve?path=${encodeURIComponent(htmlPath)}`;
}
