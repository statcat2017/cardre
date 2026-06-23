import { useState, useRef, useEffect, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

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
}

interface RunOptions {
  run_scope?: "full_plan" | "branch" | "to_node";
  target_step_id?: string;
  branch_id?: string;
}

interface UseRunProgressReturn extends RunProgressState {
  startRun: (planVersionId: string, options?: RunOptions) => Promise<void>;
  addDiagnostic: (msg: string) => void;
}

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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (pollRef.current !== null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, []);

  const addDiagnostic = useCallback((msg: string) => {
    setDiagnostics((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  }, []);

  const startRun = useCallback(async (planVersionId: string, options?: RunOptions) => {
    setRunning(true);
    setError(null);
    setLiveDiagnostic(null);

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

      let consecutiveErrors = 0;
      const MAX_CONSECUTIVE_ERRORS = 5;

      const checkProgress = async () => {
        if (!mountedRef.current) return;
        try {
          const [run, steps] = await Promise.all([
            api.getRun(runId),
            api.getRunSteps(runId),
          ]);
          consecutiveErrors = 0;
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
          // Replace live diagnostic on each poll instead of appending
          setLiveDiagnostic(`steps: [${stepStatuses.join(", ")}]`);

          if (run.status !== "running") {
            if (pollRef.current !== null) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
            queryClient.invalidateQueries({ queryKey: ["project", projectId] });
            queryClient.invalidateQueries({ queryKey: ["projectRuns", projectId] });
            setRunning(false);
            setLiveStepStatus({});
            setLiveDiagnostic(null);
            addDiagnostic(`Run ${run.status}`);
            onRunComplete();
          }
        } catch {
          consecutiveErrors++;
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            if (pollRef.current !== null) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
            setRunning(false);
            setError("Run polling failed after multiple retries.");
            addDiagnostic(`Polling failed after ${MAX_CONSECUTIVE_ERRORS} consecutive errors`);
          }
        }
      };

      pollRef.current = setInterval(checkProgress, 2000);
    } catch (e: any) {
      setError(e.message);
      addDiagnostic(`Run failed: ${e.message}`);
      setRunning(false);
    }
  }, [projectId, queryClient, addDiagnostic, onRunComplete]);

  const progressCompleted = Object.values(liveStepStatus).filter((s) =>
    ["succeeded", "failed", "cancelled"].includes(s)
  ).length;
  const stepProgress = running && totalPlanSteps > 0
    ? { completed: progressCompleted, total: totalPlanSteps }
    : null;

  return {
    running,
    error,
    carriedForwardSteps,
    liveStepStatus,
    stepProgress,
    diagnostics,
    liveDiagnostic,
    startRun,
    addDiagnostic,
  };
}
