import { useState, useRef, useEffect, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, isApiError, formatApiError, type ApiError } from "../api/client";

interface StepProgress {
  completed: number;
  total: number;
}

interface RunProgressState {
  running: boolean;
  error: string | null;
  carriedForwardSteps: Record<string, boolean>;
  liveStepStatus: Record<string, string>;
  stepProgress: StepProgress | null;
  diagnostics: string[];
  liveDiagnostic: string | null;
  runStalled: boolean;
}

interface RunOptions {
  run_scope?: "full_plan" | "branch" | "to_node";
  target_step_id?: string;
  branch_id?: string;
}

interface UseRunProgressReturn extends RunProgressState {
  startRun: (planVersionId: string, options?: RunOptions) => Promise<void>;
  stopWatchingRun: () => void;
  addDiagnostic: (msg: string) => void;
  lastPollError: ApiError | null;
  lastRunError: string | null;
}

const POLL_INTERVAL_MS = 2000;
const MAX_CONSECUTIVE_ERRORS = 5;
const STALL_POLL_LIMIT = 30; // ~60s without progress

export function useRunProgress(
  projectId: string,
  onRunComplete: () => void,
): UseRunProgressReturn {
  const queryClient = useQueryClient();
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [carriedForwardSteps, setCarriedForwardSteps] = useState<Record<string, boolean>>({});
  const [liveStepStatus, setLiveStepStatus] = useState<Record<string, string>>({});
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [liveDiagnostic, setLiveDiagnostic] = useState<string | null>(null);
  const [totalPlanSteps, setTotalPlanSteps] = useState(0);
  const [lastPollError, setLastPollError] = useState<ApiError | null>(null);
  const [lastRunError, setLastRunError] = useState<string | null>(null);
  const [runStalled, setRunStalled] = useState(false);

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const consecutiveErrorsRef = useRef(0);
  const stallCountRef = useRef(0);
  const lastStepSnapshotRef = useRef("");

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const stopPolling = useCallback(() => {
    clearPollTimer();
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, [clearPollTimer]);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      stopPolling();
    };
  }, [stopPolling]);

  const addDiagnostic = useCallback((msg: string) => {
    setDiagnostics((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  }, []);

  const stopWatchingRun = useCallback(() => {
    stopPolling();
    setRunning(false);
    setError("Stopped watching run (backend execution continues).");
    setCarriedForwardSteps({});
    setLiveStepStatus({});
    setLiveDiagnostic(null);
    addDiagnostic("Stopped watching run — backend execution continues");
  }, [stopPolling, addDiagnostic]);

  const startRun = useCallback(async (planVersionId: string, options?: RunOptions) => {
    setRunning(true);
    setError(null);
    setRunStalled(false);
    setLiveDiagnostic(null);
    setCarriedForwardSteps({});
    setLiveStepStatus({});
    setTotalPlanSteps(0);
    setLastPollError(null);
    setLastRunError(null);
    consecutiveErrorsRef.current = 0;
    stallCountRef.current = 0;
    lastStepSnapshotRef.current = "";

    // Health gate: check sidecar is reachable before attempting run
    try {
      await api.health();
    } catch (e: unknown) {
      const msg = isApiError(e) ? formatApiError(e) : String(e);
      setError(msg);
      addDiagnostic(`Sidecar unreachable: ${msg}`);
      setRunning(false);
      return;
    }

    try {
      const runResp = await api.runPlan({
        project_id: projectId,
        plan_version_id: planVersionId,
        run_scope: options?.run_scope ?? "full_plan",
        force: false,
        ...(options?.target_step_id ? { target_step_id: options.target_step_id } : {}),
        ...(options?.branch_id ? { branch_id: options.branch_id } : {}),
      });
      const runId = runResp.run_id;
      addDiagnostic(`Run started (${runId.slice(0, 8)}…)`);

      queryClient.invalidateQueries({ queryKey: ["projectRuns", projectId] });

      const scheduleNextPoll = () => {
        if (!mountedRef.current) return;
        pollTimerRef.current = setTimeout(() => {
          pollOnce();
        }, POLL_INTERVAL_MS);
      };

      const pollOnce = async () => {
        if (!mountedRef.current) return;

        const pollAbort = new AbortController();
        abortRef.current = pollAbort;

        try {
          const [run, steps] = await Promise.all([
            api.getProjectRun(projectId, runId, { signal: pollAbort.signal }),
            api.getProjectRunSteps(projectId, runId, { signal: pollAbort.signal }),
          ]);

          if (!mountedRef.current) return;

          consecutiveErrorsRef.current = 0;
          setLastPollError(null);

          const cfMap: Record<string, boolean> = {};
          const liveMap: Record<string, string> = {};
          steps.steps.forEach((s) => {
            cfMap[s.step_id] = s.is_carried_forward ?? false;
            liveMap[s.step_id] = s.status;
          });
          setCarriedForwardSteps(cfMap);
          setLiveStepStatus(liveMap);
          setTotalPlanSteps(steps.steps.length);

          const stepStatuses = steps.steps.map(
            (s) => `${s.step_id}: ${s.status}${s.is_carried_forward ? " (carried forward)" : ""}`
          );
          setLiveDiagnostic(`steps: [${stepStatuses.join(", ")}]`);

          // Stall detection: track whether step statuses have changed
          const snapshot = stepStatuses.join("|");
          if (snapshot !== lastStepSnapshotRef.current) {
            lastStepSnapshotRef.current = snapshot;
            stallCountRef.current = 0;
            setRunStalled(false);
          } else {
            stallCountRef.current++;
            if (stallCountRef.current >= STALL_POLL_LIMIT && run.status === "running") {
              // Warn but keep polling — a long-running step is legitimate
              setRunStalled(true);
              if (stallCountRef.current === STALL_POLL_LIMIT) {
                addDiagnostic("Warning: no step progress for ~60s — still checking");
              }
            }
          }

          if (run.status !== "running") {
            stopPolling();
            queryClient.invalidateQueries({ queryKey: ["project", projectId] });
            queryClient.invalidateQueries({ queryKey: ["projectRuns", projectId] });
            setRunning(false);
            setCarriedForwardSteps({});
            setLiveStepStatus({});
            setLiveDiagnostic(null);
            addDiagnostic(`Run ${run.status}`);
            if (run.status === "failed") {
              if (run.latest_error) {
                const errMsg = `${run.latest_error.code}: ${run.latest_error.message}`;
                setLastRunError(errMsg);
                addDiagnostic(errMsg);
              }
              const firstStepError = steps.steps.find((s) => (s.errors ?? []).length > 0);
              if (firstStepError && (firstStepError.errors ?? []).length > 0) {
                const stepErr = firstStepError.errors![0];
                const stepErrMsg = `Step ${firstStepError.step_id}: ${stepErr.code || "ERROR"}: ${stepErr.message || stepErr.traceback || ""}`;
                setLastRunError((prev) => prev ? `${prev}\n${stepErrMsg}` : stepErrMsg);
                addDiagnostic(stepErrMsg);
              }
            }
            onRunComplete();
            return;
          }

          scheduleNextPoll();
        } catch (e: unknown) {
          if (!mountedRef.current) return;

          // If the poll was aborted (cancel), don't treat as error
          if (isApiError(e) && (e as ApiError).code === "REQUEST_ABORTED") {
            return;
          }

          consecutiveErrorsRef.current++;
          const pollErr = isApiError(e) ? e : null;
          setLastPollError(pollErr);
          if (pollErr?.requestId) {
            addDiagnostic(`Poll error (${pollErr.code}, req=${pollErr.requestId.slice(0, 8)}): ${pollErr.message}`);
          } else {
            addDiagnostic(`Poll error (${isApiError(e) ? (e as ApiError).code : "UNKNOWN"}): ${isApiError(e) ? (e as ApiError).message : String(e)}`);
          }

          if (consecutiveErrorsRef.current >= MAX_CONSECUTIVE_ERRORS) {
            stopPolling();
            setRunning(false);
            setError("Run polling failed after multiple retries.");
            addDiagnostic(`Polling failed after ${MAX_CONSECUTIVE_ERRORS} consecutive errors`);
            onRunComplete();
            return;
          }

          scheduleNextPoll();
        }
      };

      scheduleNextPoll();
    } catch (e: any) {
      const msg = isApiError(e) ? formatApiError(e) : e.message;
      setError(msg);
      addDiagnostic(`Run failed: ${msg}`);
      setRunning(false);
    }
  }, [projectId, queryClient, addDiagnostic, onRunComplete, stopPolling]);

  const progressCompleted = Object.values(liveStepStatus).filter((s) =>
    ["succeeded", "failed", "cancelled"].includes(s)
  ).length;
  const stepProgress = running && totalPlanSteps > 0
    ? { completed: progressCompleted, total: totalPlanSteps }
    : null;

  return {
    running,
    error,
    runStalled,
    carriedForwardSteps,
    liveStepStatus,
    stepProgress,
    diagnostics,
    liveDiagnostic,
    startRun,
    stopWatchingRun,
    addDiagnostic,
    lastPollError,
    lastRunError,
  };
}
