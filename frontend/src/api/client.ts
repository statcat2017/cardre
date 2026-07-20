/**
 * Robust HTTP client for the Cardre v2 API.
 *
 * Ported from v1's fetchJson<T> + ApiError with canonical error codes.
 * Uses openapi-fetch for generated path/request/response typing.
 */

import type { paths, components } from "./schema.d";
import createClient from "openapi-fetch";
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
// Transport layer — shared by fetchJson and openapi-fetch adapters
// ---------------------------------------------------------------------------

export interface FetchOptions extends Omit<RequestInit, "body"> {
  timeoutMs?: number;
  signal?: AbortSignal;
  body?: unknown;
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  const contentType = response.headers.get("content-type") ?? "";
  const bodyText = await response.text();

  if (contentType.includes("json") && bodyText) {
    try {
      const parsed = JSON.parse(bodyText);
      const detail = parsed?.detail ?? parsed;
      const rawCode = detail?.code;
      const code: ErrorCode = isErrorCode(rawCode) ? rawCode : ErrorCodes.NON_JSON_ERROR_RESPONSE;
      const context: Record<string, unknown> = detail?.context ?? {};
      if (rawCode !== undefined && !isErrorCode(rawCode)) {
        context.originalCode = rawCode;
      }
      return new ApiError(code, detail?.message ?? response.statusText, response.status, context);
    } catch {
      // fall through
    }
  }

  if (contentType.includes("html")) {
    return new ApiError(
      ErrorCodes.HTML_ERROR_RESPONSE,
      `Server returned HTML (HTTP ${response.status})`,
      response.status,
    );
  }
  if (bodyText) {
    return new ApiError(
      ErrorCodes.NON_JSON_ERROR_RESPONSE,
      bodyText.slice(0, 500),
      response.status,
    );
  }
  return new ApiError(
    ErrorCodes.EMPTY_ERROR_RESPONSE,
    response.statusText || "Empty error response",
    response.status,
  );
}

function networkError(err: unknown, url: RequestInfo | URL, timeoutMs: number): ApiError {
  if (err instanceof DOMException && err.name === "TimeoutError") {
    return new ApiError(
      ErrorCodes.REQUEST_TIMEOUT,
      `Request to ${url} timed out after ${timeoutMs}ms`,
      408,
    );
  }
  if (err instanceof DOMException && err.name === "AbortError") {
    return new ApiError(ErrorCodes.REQUEST_ABORTED, `Request to ${url} was aborted`, 499);
  }
  return new ApiError(
    ErrorCodes.SIDECAR_UNREACHABLE,
    `Cannot reach ${url}: ${(err as Error).message ?? "network error"}`,
    503,
  );
}

export async function fetchResponse(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const req = input instanceof Request ? input : undefined;
  const timeoutMs = (init as FetchOptions | undefined)?.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
  const externalSignal = req?.signal ?? init?.signal;

  const controller = new AbortController();
  const timeoutId =
    timeoutMs > 0
      ? setTimeout(() => controller.abort(new DOMException("Timeout", "TimeoutError")), timeoutMs)
      : undefined;

  const onExternalAbort = () => controller.abort(externalSignal!.reason);
  if (externalSignal && externalSignal !== controller.signal) {
    externalSignal.addEventListener("abort", onExternalAbort, { once: true });
  }

  try {
    let response: Response;

    if (req) {
      // openapi-fetch path: construct a new Request from the original to
      // preserve its body ReadableStream without needing `duplex: "half"`.
      const headers = new Headers(req.headers);
      headers.set("Accept", "application/json");
      const forwarded = new Request(req, { headers, signal: controller.signal });
      try {
        response = await fetch(forwarded);
      } catch (err: unknown) {
        throw networkError(err, input, timeoutMs);
      }
    } else {
      const opts = init as FetchOptions | undefined;
      const rawBody = opts?.body;
      const body: BodyInit | null | undefined =
        rawBody !== undefined ? JSON.stringify(rawBody) : init?.body;

      const headers = new Headers(init?.headers);
      headers.set("Accept", "application/json");
      if (rawBody !== undefined) {
        headers.set("Content-Type", "application/json");
      }

      try {
        response = await fetch(input, {
          method: init?.method,
          headers,
          body,
          signal: controller.signal,
        });
      } catch (err: unknown) {
        throw networkError(err, input, timeoutMs);
      }
    }

    if (!response.ok) {
      throw await errorFromResponse(response);
    }

    return response;
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }
}

export async function fetchJson<T>(url: string, options: FetchOptions = {}): Promise<T> {
  const response = await fetchResponse(url, options as RequestInit);

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
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
    throw new ApiError(ErrorCodes.MALFORMED_JSON_RESPONSE, "Response body is not valid JSON", 502);
  }
}

// ---------------------------------------------------------------------------
// openapi-fetch adapter & helpers
// ---------------------------------------------------------------------------

async function typedTransport(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const response = await fetchResponse(input, init);

  if (response.status === 204) {
    return response;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) {
    throw new ApiError(
      ErrorCodes.MALFORMED_JSON_RESPONSE,
      `Expected JSON but got ${contentType}`,
      502,
    );
  }
  const text = await response.clone().text();
  if (!text) {
    throw new ApiError(ErrorCodes.EMPTY_OK_BODY, "Response was 200 OK with empty body", 502);
  }
  try {
    JSON.parse(text);
  } catch {
    throw new ApiError(ErrorCodes.MALFORMED_JSON_RESPONSE, "Response body is not valid JSON", 502);
  }
  return response;
}

function getBaseUrl(): string {
  return (
    (window as unknown as { __API_URL__?: string }).__API_URL__ || "http://127.0.0.1:8752"
  ).replace(/\/$/, "");
}

function makeClient() {
  return createClient<paths>({ baseUrl: getBaseUrl(), fetch: typedTransport });
}

function requireData<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data;
  if (result.error instanceof ApiError) throw result.error;
  throw new ApiError(
    ErrorCodes.NON_JSON_ERROR_RESPONSE,
    `API operation failed`,
    result.response.status,
  );
}

const projectHeaders = (projectId: string) => ({
  "X-Project-Id": projectId,
});

// ---------------------------------------------------------------------------
// API wrapper
// ---------------------------------------------------------------------------

export type ProjectScope = {
  projectId: string;
};

export const api = {
  listProjects: async () => {
    const client = makeClient();
    return requireData(await client.GET("/projects"));
  },
  createProject: async (body: components["schemas"]["ProjectCreateRequest"]) => {
    const client = makeClient();
    return requireData(await client.POST("/projects", { body }));
  },
  getProject: async (projectId: string) => {
    const client = makeClient();
    return requireData(
      await client.GET("/projects/{project_id}", {
        params: { path: { project_id: projectId } },
      }),
    );
  },
  forProject: (scope: ProjectScope) => {
    const pid = scope.projectId;
    return {
      listPlans: async () => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/plans", {
            params: {
              path: { project_id: pid },
              header: projectHeaders(pid),
            },
          }),
        );
      },
      createPlan: async (body: components["schemas"]["PlanCreateRequest"]) => {
        const client = makeClient();
        return requireData(
          await client.POST("/projects/{project_id}/plans", {
            params: {
              path: { project_id: pid },
              header: projectHeaders(pid),
            },
            body,
          }),
        );
      },
      getPlan: async (planId: string) => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/plans/{plan_id}", {
            params: {
              path: { project_id: pid, plan_id: planId },
              header: projectHeaders(pid),
            },
          }),
        );
      },
      listPlanVersions: async (planId: string) => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/plans/{plan_id}/versions", {
            params: {
              path: { project_id: pid, plan_id: planId },
              header: projectHeaders(pid),
            },
          }),
        );
      },
      getPlanVersion: async (planVersionId: string) => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/plan-versions/{plan_version_id}", {
            params: {
              path: { project_id: pid, plan_version_id: planVersionId },
              header: projectHeaders(pid),
            },
          }),
        );
      },
      createRun: async (body: components["schemas"]["RunCreateRequest"]) => {
        const client = makeClient();
        return requireData(
          await client.POST("/projects/{project_id}/runs", {
            params: {
              path: { project_id: pid },
              header: projectHeaders(pid),
            },
            body,
          }),
        );
      },
      listRuns: async () => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/runs", {
            params: {
              path: { project_id: pid },
              header: projectHeaders(pid),
            },
          }),
        );
      },
      getRun: async (runId: string) => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/runs/{run_id}", {
            params: {
              path: { project_id: pid, run_id: runId },
              header: projectHeaders(pid),
            },
          }),
        );
      },
      listRunSteps: async (runId: string) => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/runs/{run_id}/steps", {
            params: {
              path: { project_id: pid, run_id: runId },
              header: projectHeaders(pid),
            },
          }),
        );
      },
      listRunEvidence: async (runId: string) => {
        const client = makeClient();
        return requireData(
          await client.GET("/projects/{project_id}/runs/{run_id}/evidence", {
            params: {
              path: { project_id: pid, run_id: runId },
              header: projectHeaders(pid),
            },
          }),
        );
      },
    };
  },
};
