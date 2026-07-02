/**
 * Robust HTTP client for the Cardre v2 API.
 *
 * Ported from v1's fetchJson<T> + ApiError with canonical error codes.
 */

import type { components } from "./schema.d";

// ---------------------------------------------------------------------------
// Canonical error codes (mirrors cardre/api/errors.py)
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
} as const;

// ---------------------------------------------------------------------------
// ApiError
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly context: Record<string, unknown>;

  constructor(
    code: string,
    message: string,
    status: number = 500,
    context: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.context = context;
  }

  get detail(): string {
    return `${this.code}: ${this.message} (HTTP ${this.status})`;
  }
}

// ---------------------------------------------------------------------------
// Typed fetch
// ---------------------------------------------------------------------------

export interface FetchOptions extends Omit<RequestInit, "body"> {
  /** Default 30_000 */
  timeoutMs?: number;
  /** Signal preempts the timeout */
  signal?: AbortSignal;
  /** JSON body — sets Content-Type and serialises */
  body?: unknown;
}

export async function fetchJson<T>(url: string, options: FetchOptions = {}): Promise<T> {
  const { timeoutMs = 30_000, signal: externalSignal, body, ...init } = options;

  // Build composite signal (external + timeout)
  const controller = new AbortController();
  const timeoutId =
    timeoutMs > 0
      ? setTimeout(() => controller.abort(new DOMException("Timeout", "TimeoutError")), timeoutMs)
      : undefined;

  const onExternalAbort = () => controller.abort(externalSignal!.reason);
  if (externalSignal) {
    externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }

  try {
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(init.headers as Record<string, string> | undefined),
    };

    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    let response: Response;
    try {
      response = await fetch(url, {
        ...init,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "TimeoutError") {
        throw new ApiError(
          ErrorCodes.REQUEST_TIMEOUT,
          `Request to ${url} timed out after ${timeoutMs}ms`,
          408,
        );
      }
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new ApiError(ErrorCodes.REQUEST_ABORTED, `Request to ${url} was aborted`, 499);
      }
      throw new ApiError(
        ErrorCodes.SIDECAR_UNREACHABLE,
        `Cannot reach ${url}: ${(err as Error).message ?? "network error"}`,
        503,
      );
    }

    const contentType = response.headers.get("content-type") ?? "";

    if (!response.ok) {
      const isJson = contentType.includes("json");
      const bodyText = await response.text();

      // Try to parse structured error
      if (isJson && bodyText) {
        try {
          const parsed = JSON.parse(bodyText);
          const detail = parsed?.detail ?? parsed;
          throw new ApiError(
            detail?.code ?? "HTTP_ERROR",
            detail?.message ?? response.statusText,
            response.status,
            detail?.context ?? {},
          );
        } catch (parseErr) {
          // Re-throw ApiError (thrown above on success), fall through on parse failure
          if (parseErr instanceof ApiError) {
            throw parseErr;
          }
        }
      }

      // HTML error
      if (contentType.includes("html")) {
        throw new ApiError(
          ErrorCodes.HTML_ERROR_RESPONSE,
          `Server returned HTML (HTTP ${response.status})`,
          response.status,
        );
      }

      // Non-JSON error
      if (bodyText) {
        throw new ApiError(
          ErrorCodes.NON_JSON_ERROR_RESPONSE,
          bodyText.slice(0, 500),
          response.status,
        );
      }

      throw new ApiError(
        ErrorCodes.EMPTY_ERROR_RESPONSE,
        response.statusText || "Empty error response",
        response.status,
      );
    }

    // 204 No Content
    if (response.status === 204) {
      return undefined as unknown as T;
    }

    // Parse JSON body
    if (!contentType.includes("json")) {
      throw new ApiError(
        ErrorCodes.MALFORMED_JSON_RESPONSE,
        `Expected JSON but got ${contentType}`,
        502,
      );
    }

    const text = await response.text();
    if (!text) {
      throw new ApiError(ErrorCodes.EMPTY_OK_BODY, "Response was 200 OK with empty body", 502);
    }

    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError(
        ErrorCodes.MALFORMED_JSON_RESPONSE,
        "Response body is not valid JSON",
        502,
      );
    }
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }
}

// ---------------------------------------------------------------------------
// API wrapper
// ---------------------------------------------------------------------------

type ProjectScopedOptions = {
  projectPath: string;
};

function getBaseUrl(): string {
  return (
    (window as unknown as { __API_URL__?: string }).__API_URL__ || "http://127.0.0.1:8752"
  ).replace(/\/$/, "");
}

function projectHeaders(projectPath: string): Record<string, string> {
  return { "X-Project-Path": projectPath };
}

function url(path: string): string {
  return `${getBaseUrl()}${path}`;
}

export const api = {
  listProjects: (options: ProjectScopedOptions) =>
    fetchJson<components["schemas"]["ProjectListResponse"]>(url("/projects"), {
      headers: projectHeaders(options.projectPath),
    }),
  createProject: (
    options: ProjectScopedOptions,
    body: components["schemas"]["ProjectCreateRequest"],
  ) =>
    fetchJson<components["schemas"]["ProjectResponse"]>(url("/projects"), {
      method: "POST",
      headers: projectHeaders(options.projectPath),
      body,
    }),
  getProject: (options: ProjectScopedOptions, projectId: string) =>
    fetchJson<components["schemas"]["ProjectResponse"]>(url(`/projects/${projectId}`), {
      headers: projectHeaders(options.projectPath),
    }),
  listPlans: (options: ProjectScopedOptions, projectId: string) =>
    fetchJson<components["schemas"]["PlanListResponse"]>(url(`/projects/${projectId}/plans`), {
      headers: projectHeaders(options.projectPath),
    }),
  createPlan: (
    options: ProjectScopedOptions,
    projectId: string,
    body: components["schemas"]["PlanCreateRequest"],
  ) =>
    fetchJson<components["schemas"]["PlanResponse"]>(url(`/projects/${projectId}/plans`), {
      method: "POST",
      headers: projectHeaders(options.projectPath),
      body,
    }),
  getPlan: (options: ProjectScopedOptions, projectId: string, planId: string) =>
    fetchJson<components["schemas"]["PlanResponse"]>(
      url(`/projects/${projectId}/plans/${planId}`),
      {
        headers: projectHeaders(options.projectPath),
      },
    ),
  listPlanVersions: (options: ProjectScopedOptions, projectId: string, planId: string) =>
    fetchJson<components["schemas"]["PlanVersionListResponse"]>(
      url(`/projects/${projectId}/plans/${planId}/versions`),
      { headers: projectHeaders(options.projectPath) },
    ),
  getPlanVersion: (options: ProjectScopedOptions, projectId: string, planVersionId: string) =>
    fetchJson<components["schemas"]["PlanVersionResponse"]>(
      url(`/projects/${projectId}/plan-versions/${planVersionId}`),
      { headers: projectHeaders(options.projectPath) },
    ),
  createRun: (
    options: ProjectScopedOptions,
    projectId: string,
    body: components["schemas"]["RunCreateRequest"],
  ) =>
    fetchJson<components["schemas"]["RunResponse"]>(url(`/projects/${projectId}/runs`), {
      method: "POST",
      headers: projectHeaders(options.projectPath),
      body,
    }),
  listRuns: (options: ProjectScopedOptions, projectId: string) =>
    fetchJson<components["schemas"]["RunListResponse"]>(url(`/projects/${projectId}/runs`), {
      headers: projectHeaders(options.projectPath),
    }),
  getRun: (options: ProjectScopedOptions, projectId: string, runId: string) =>
    fetchJson<components["schemas"]["RunResponse"]>(url(`/projects/${projectId}/runs/${runId}`), {
      headers: projectHeaders(options.projectPath),
    }),
  listRunSteps: (options: ProjectScopedOptions, projectId: string, runId: string) =>
    fetchJson<components["schemas"]["RunStepResponse"][]>(
      url(`/projects/${projectId}/runs/${runId}/steps`),
      { headers: projectHeaders(options.projectPath) },
    ),
  listRunEvidence: (options: ProjectScopedOptions, projectId: string, runId: string) =>
    fetchJson<components["schemas"]["EvidenceEdgeResponse"][]>(
      url(`/projects/${projectId}/runs/${runId}/evidence`),
      { headers: projectHeaders(options.projectPath) },
    ),
};
