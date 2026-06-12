import type {
  ArtifactResponse,
  CreateProjectBody,
  HealthResponse,
  ImportBody,
  PlanResponse,
  ProjectDetailResponse,
  ProjectResponse,
  RunBody,
  RunResponse,
  RunStepsResponse,
} from "../types";

function getBaseUrl(): string {
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

  importDataset: (body: ImportBody) =>
    fetchJson<ArtifactResponse>("/datasets/import", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getPlan: (id: string) => fetchJson<PlanResponse>(`/plans/${id}`),

  runPlan: (body: RunBody) =>
    fetchJson<RunResponse>("/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getRun: (id: string) => fetchJson<RunResponse>(`/runs/${id}`),

  getRunSteps: (id: string) => fetchJson<RunStepsResponse>(`/runs/${id}/steps`),

  getArtifact: (id: string) => fetchJson<ArtifactResponse>(`/artifacts/${id}`),
};
