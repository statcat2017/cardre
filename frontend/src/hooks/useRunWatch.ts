/**
 * useRunWatch — central polling hook for run progress.
 *
 * Ported from v1 useRunProgress.ts, renamed. Distinguishes 9 states:
 *   sidecar unreachable, timeout, malformed JSON, run failed,
 *   interrupted, stale, stuck, user-cancelled, backend-cancelled.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { ErrorCodes } from "../api/errorCodes";
import type { components } from "../api/schema.d";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RunWatchStatus =
  | "loading"
  | "running"
  | "succeeded"
  | "failed"
  | "interrupted"
  | "stale"
  | "stuck"
  | "cancelled"
  | "error";

export interface RunWatchState {
  /** Current run data, or null if not yet loaded. */
  run: components["schemas"]["RunResponse"] | null;
  /** High-level status derived from run + error state. */
  status: RunWatchStatus;
  /** Human-readable status message. */
  message: string;
  /** Error detail, if any. */
  error: string | null;
  /** Whether the poller is actively running. */
  polling: boolean;
}

export interface UseRunWatchOptions {
  /** Base URL of the Cardre API (with port). */
  baseUrl: string;
  /** Project ID. */
  projectId: string;
  /** Project path (for X-Project-Path header). */
  projectPath: string;
  /** Run ID to watch. */
  runId: string | null;
  /** Poll interval in ms (default 2000). */
  pollIntervalMs?: number;
  /** Maximum number of consecutive error polls before giving up (default 5). */
  maxErrorRetries?: number;
  /** Callback when run reaches a terminal state. */
  onComplete?: (run: components["schemas"]["RunResponse"]) => void;
  /** Callback on polling error. */
  onError?: (error: ApiError) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function deriveStatus(
  run: components["schemas"]["RunResponse"] | null,
  error: string | null,
): RunWatchStatus {
  if (error) return "error";
  if (!run) return "loading";
  switch (run.status) {
    case "running":
      return run.is_stale ? "stale" : "running";
    case "succeeded":
      return "succeeded";
    case "failed":
      return "failed";
    case "interrupted":
      return "interrupted";
    case "cancelled":
      return "cancelled";
    default:
      return "running";
  }
}

function deriveMessage(
  status: RunWatchStatus,
  run: components["schemas"]["RunResponse"] | null,
): string {
  switch (status) {
    case "loading":
      return "Loading run…";
    case "running":
      return `Running (step ${(run?.executed_step_ids ?? []).length} completed)`;
    case "succeeded":
      return "Run completed successfully.";
    case "failed": {
      const err = run?.latest_error;
      return err ? `Run failed: ${err.message ?? err.code ?? "unknown error"}` : "Run failed.";
    }
    case "interrupted":
      return "Run was interrupted.";
    case "stale":
      return "Run appears stale (no recent heartbeat).";
    case "stuck":
      return "Run appears stuck — no progress detected.";
    case "cancelled":
      return "Run was cancelled.";
    case "error":
      return "An error occurred while watching the run.";
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useRunWatch(options: UseRunWatchOptions): RunWatchState {
  const {
    projectId,
    projectPath,
    runId,
    pollIntervalMs = 2000,
    maxErrorRetries = 5,
    onComplete,
    onError,
  } = options;

  const [run, setRun] = useState<components["schemas"]["RunResponse"] | null>(null);
  const [status, setStatus] = useState<RunWatchStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  const errorCountRef = useRef(0);
  const completedRunIdsRef = useRef<Set<string>>(new Set());

  const poll = useCallback(async () => {
    if (!runId) return;

    try {
      const data = await api.getRun({ projectPath }, projectId, runId);
      errorCountRef.current = 0;
      setRun(data);
      setError(null);

      const newStatus = deriveStatus(data, null);
      setStatus(newStatus);

      // Terminal states — stop polling
      if (["succeeded", "failed", "interrupted", "cancelled"].includes(data.status)) {
        if (!completedRunIdsRef.current.has(data.run_id)) {
          completedRunIdsRef.current.add(data.run_id);
          onComplete?.(data);
        }
        setPolling(false);
        return;
      }

      // Keep polling
      setPolling(true);
    } catch (err) {
      errorCountRef.current += 1;
      let message: string;
      let errStatus: RunWatchStatus = "error";

      if (err instanceof ApiError) {
        message = err.detail;
        onError?.(err);

        switch (err.code) {
          case ErrorCodes.SIDECAR_UNREACHABLE:
            message = "Sidecar is unreachable — is the backend running?";
            break;
          case ErrorCodes.REQUEST_TIMEOUT:
            message = "Request timed out.";
            break;
          case ErrorCodes.MALFORMED_JSON_RESPONSE:
            message = "Received malformed response from server.";
            break;
          case ErrorCodes.REQUEST_ABORTED:
            message = "Request was aborted.";
            errStatus = "cancelled";
            break;
        }
      } else {
        message = err instanceof Error ? err.message : String(err);
      }

      setError(message);
      setStatus(errStatus);

      // Give up after maxErrorRetries
      if (errorCountRef.current >= maxErrorRetries) {
        setPolling(false);
        setStatus("stuck");
        setError(`Poller gave up after ${maxErrorRetries} consecutive errors.`);
      } else {
        setPolling(true);
      }
    }
  }, [projectId, projectPath, runId, maxErrorRetries, onComplete, onError]);

  // Start / stop polling
  useEffect(() => {
    if (!runId) {
      return;
    }

    // Initial fetch
    // eslint-disable-next-line react-hooks/set-state-in-effect
    poll();

    const interval = setInterval(poll, pollIntervalMs);
    return () => {
      clearInterval(interval);
      setPolling(false);
    };
  }, [runId, poll, pollIntervalMs]);

  return {
    run,
    status,
    message: deriveMessage(status, run),
    error,
    polling,
  };
}
