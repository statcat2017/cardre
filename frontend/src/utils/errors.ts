import { isApiError } from "../api/client";

export interface RenderableError {
  code: string;
  message: string;
  context?: Record<string, unknown>;
  diagnostics?: Array<{ code: string; message: string }>;
}

export function renderApiError(err: unknown): RenderableError | null {
  if (!isApiError(err)) return null;
  return {
    code: err.detail.code,
    message: err.detail.message,
    context: err.detail.context,
    diagnostics: err.detail.diagnostics,
  };
}

export interface RecoveryInfo {
  kind: "user_fixable" | "developer_fixable" | "retryable" | "fatal";
  title: string;
  message: string;
  action?: { label: string; description: string };
  retryable: boolean;
  requestId?: string;
  errorId?: string;
  diagnostics?: Array<{ code: string; message: string }>;
}

const CODE_COPY: Record<string, Omit<RecoveryInfo, "requestId" | "errorId" | "diagnostics">> & {
  _default: Omit<RecoveryInfo, "requestId" | "errorId" | "diagnostics">;
} = {
  _default: {
    kind: "fatal",
    title: "Something went wrong",
    message: "",
    retryable: false,
  },
  SIDECAR_UNREACHABLE: {
    kind: "developer_fixable",
    title: "Can't reach the Cardre engine",
    message: "The sidecar service is not running or refused the connection. Start it and retry.",
    action: { label: "Retry", description: "Re-attempt the request" },
    retryable: true,
  },
  REQUEST_TIMEOUT: {
    kind: "retryable",
    title: "The request timed out",
    message: "The engine took too long to respond. Try again \u2014 if it persists, the operation may be too large.",
    action: { label: "Retry", description: "Re-attempt the request" },
    retryable: true,
  },
  REQUEST_ABORTED: {
    kind: "retryable",
    title: "Request was cancelled",
    message: "The request was cancelled.",
    retryable: true,
  },
  PLAN_CONTAINS_UNAVAILABLE_NODES: {
    kind: "user_fixable",
    title: "This plan can't run yet",
    message: "One or more steps reference nodes that aren't available. See the step list below.",
    retryable: false,
  },
  OPTIONAL_DEPENDENCY_NOT_INSTALLED: {
    kind: "user_fixable",
    title: "Missing optional dependency",
    message: "This node needs an extra package installed.",
    retryable: false,
  },
  GOVERNANCE_NOT_ENABLED: {
    kind: "developer_fixable",
    title: "Governance mode is off",
    message: "Challenger branches require CARDRE_GOVERNANCE=1. Restart the sidecar with that environment variable set.",
    retryable: false,
  },
  ARTIFACT_NOT_FOUND: {
    kind: "user_fixable",
    title: "Artifact not found",
    message: "This artifact may have been deleted or belongs to another project.",
    action: { label: "Refresh artifacts", description: "Reload the artifact list" },
    retryable: true,
  },
  RUN_DISPATCH_FAILED: {
    kind: "retryable",
    title: "Couldn't start the background run",
    message: "The engine failed to launch the run worker. This is usually transient \u2014 try again.",
    action: { label: "Retry", description: "Re-attempt the run" },
    retryable: true,
  },
  RUN_EXECUTION_FAILED: {
    kind: "retryable",
    title: "Run failed",
    message: "A step raised an error during execution. See the step's error details below.",
    action: { label: "Retry from failed step", description: "Re-run from the failing step" },
    retryable: true,
  },
  RUN_SHORT_CIRCUITED: {
    kind: "retryable",
    title: "Run skipped \u2014 already current",
    message: "This run had no stale steps, so no work was needed.",
    retryable: false,
  },
  NODE_NOT_AVAILABLE_FOR_LAUNCH: {
    kind: "user_fixable",
    title: "Node not available for launch",
    message: "This node type is deferred and can't be used in launch mode without configuration.",
    retryable: false,
  },
};

export function classifyError(e: unknown): RecoveryInfo {
  if (!isApiError(e)) {
    return {
      ...CODE_COPY._default,
      message: e instanceof Error ? e.message : String(e),
    };
  }
  const base = CODE_COPY[e.code];
  if (base) {
    return {
      ...base,
      requestId: e.requestId,
      errorId: e.detail.error_id,
      diagnostics: e.detail.diagnostics as Array<{ code: string; message: string }> | undefined,
      message: base.message || e.detail.message,
    };
  }
  const recoverable = (e.detail as Record<string, unknown>).recoverable === true;
  return {
    kind: recoverable ? "retryable" : "fatal",
    title: e.detail.message || e.code,
    message: e.detail.message,
    retryable: recoverable,
    requestId: e.requestId,
    errorId: e.detail.error_id,
    diagnostics: e.detail.diagnostics as Array<{ code: string; message: string }> | undefined,
  };
}
