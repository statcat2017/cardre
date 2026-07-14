/**
 * Robust HTTP client for the Cardre v2 API.
 *
 * Ported from v1's fetchJson<T> + ApiError with canonical error codes.
 */

import type { components } from "./schema.d";
import { ErrorCodes, isErrorCode, type ErrorCode } from "./errorCodes";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

// ---------------------------------------------------------------------------
// ApiError
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  readonly code: ErrorCode;
  readonly status: number;
  readonly context: Record<string, unknown>;

  constructor(
    code: ErrorCode,
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

export function toErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
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
  const { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, signal: externalSignal, body, ...init } = options;

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
          const rawCode = detail?.code;
          const code: ErrorCode = isErrorCode(rawCode)
            ? rawCode
            : ErrorCodes.NON_JSON_ERROR_RESPONSE;
          const context: Record<string, unknown> = detail?.context ?? {};
          if (rawCode !== undefined && !isErrorCode(rawCode)) {
            context.originalCode = rawCode;
          }
          throw new ApiError(
            code,
            detail?.message ?? response.statusText,
            response.status,
            context,
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

export type ProjectScope = {
  projectId: string;
  projectPath?: string;
};

type ProjectScopedOptions = ProjectScope;

function getBaseUrl(): string {
  return (
    (window as unknown as { __API_URL__?: string }).__API_URL__ || "http://127.0.0.1:8752"
  ).replace(/\/$/, "");
}

function projectHeaders(options: ProjectScopedOptions): Record<string, string> {
  const headers: Record<string, string> = { "X-Project-Id": options.projectId };
  if (options.projectPath) {
    headers["X-Project-Path"] = options.projectPath;
  }
  return headers;
}

function url(path: string): string {
  return `${getBaseUrl()}${path}`;
}

export const api = {
  listProjects: () => fetchJson<components["schemas"]["ProjectListResponse"]>(url("/projects"), {}),
  createProject: (body: components["schemas"]["ProjectCreateRequest"]) =>
    fetchJson<components["schemas"]["ProjectResponse"]>(url("/projects"), {
      method: "POST",
      body,
    }),
  getProject: (projectId: string) =>
    fetchJson<components["schemas"]["ProjectResponse"]>(url(`/projects/${projectId}`), {}),
  forProject: (scope: ProjectScope) => {
    const headers = projectHeaders(scope);
    const pid = scope.projectId;
    return {
      listPlans: () =>
        fetchJson<components["schemas"]["PlanListResponse"]>(url(`/projects/${pid}/plans`), { headers }),
      createPlan: (body: components["schemas"]["PlanCreateRequest"]) =>
        fetchJson<components["schemas"]["PlanResponse"]>(url(`/projects/${pid}/plans`), {
          method: "POST", headers, body,
        }),
      getPlan: (planId: string) =>
        fetchJson<components["schemas"]["PlanResponse"]>(url(`/projects/${pid}/plans/${planId}`), { headers }),
      listPlanVersions: (planId: string) =>
        fetchJson<components["schemas"]["PlanVersionListResponse"]>(
          url(`/projects/${pid}/plans/${planId}/versions`), { headers },
        ),
      getPlanVersion: (planVersionId: string) =>
        fetchJson<components["schemas"]["PlanVersionResponse"]>(
          url(`/projects/${pid}/plan-versions/${planVersionId}`), { headers },
        ),
      createRun: (body: components["schemas"]["RunCreateRequest"]) =>
        fetchJson<components["schemas"]["RunResponse"]>(url(`/projects/${pid}/runs`), {
          method: "POST", headers, body,
        }),
      listRuns: () =>
        fetchJson<components["schemas"]["RunListResponse"]>(url(`/projects/${pid}/runs`), { headers }),
      getRun: (runId: string) =>
        fetchJson<components["schemas"]["RunResponse"]>(url(`/projects/${pid}/runs/${runId}`), { headers }),
      listRunSteps: (runId: string) =>
        fetchJson<components["schemas"]["RunStepResponse"][]>(
          url(`/projects/${pid}/runs/${runId}/steps`), { headers },
        ),
      listRunEvidence: (runId: string) =>
        fetchJson<components["schemas"]["RunEvidenceEdgeResponse"][]>(
          url(`/projects/${pid}/runs/${runId}/evidence`), { headers },
        ),
    };
  },
};
