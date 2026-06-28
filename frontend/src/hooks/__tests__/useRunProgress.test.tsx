import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { useRunProgress } from "../useRunProgress";
import type { ReactNode } from "react";
import type { RunResponse, RunStepsResponse } from "../../types";

const PROJECT_ID = "prj_test";
const RUN_ID = "run_abc123";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function makeRun(status: string, overrides: Record<string, unknown> = {}) {
  return {
    run_id: RUN_ID,
    plan_version_id: "pv1",
    status,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: status !== "running" ? "2026-01-01T00:01:00Z" : null,
    step_count: 3,
    diagnostics: [],
    latest_error: null,
    ...overrides,
  };
}

function makeSteps(statuses: string[]) {
  return {
    run_id: RUN_ID,
    steps: statuses.map((s, i) => ({
      run_step_id: `rs_${i}`,
      step_id: `step_${i}`,
      node_type: "test",
      status: s,
      started_at: "2026-01-01T00:00:00Z",
      finished_at: null,
      input_artifact_ids: [],
      output_artifact_ids: [],
      warnings: [],
      errors: [],
      is_carried_forward: false,
    })),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(api, "health").mockResolvedValue({
    status: "ok",
    cardre_version: "0.1.0",
    registry_accessible: false,
    registered_node_count: 0,
    launch_node_count: 0,
    deferred_node_count: 0,
    governance_enabled: false,
    checked_at: "",
    diagnostics: [],
  });
  vi.spyOn(api, "runPlan").mockResolvedValue(makeRun("running") as unknown as RunResponse);
  vi.spyOn(api, "getProjectRun").mockResolvedValue(makeRun("running") as unknown as RunResponse);
  vi.spyOn(api, "getProjectRunSteps").mockResolvedValue(
    makeSteps(["running", "running", "running"]) as unknown as RunStepsResponse,
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("useRunProgress", () => {
  it("starts a run and polls until completion", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.startRun("pv1");
      // Let health + runPlan resolve
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.running).toBe(true);
    expect(api.runPlan).toHaveBeenCalledTimes(1);

    // First poll fires after 2000ms
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(api.getProjectRun).toHaveBeenCalledTimes(1);
    expect(api.getProjectRunSteps).toHaveBeenCalledTimes(1);

    // Second poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(api.getProjectRun).toHaveBeenCalledTimes(2);
  });

  it("stops polling when run completes with succeeded status", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    // First poll returns running, second returns succeeded
    vi.spyOn(api, "getProjectRun").mockReset();
    vi.spyOn(api, "getProjectRun")
      .mockResolvedValueOnce(makeRun("running") as unknown as RunResponse)
      .mockResolvedValue(makeRun("succeeded") as unknown as RunResponse);

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    // First poll at 2000ms
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    // Second poll at 4000ms — returns succeeded
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(result.current.running).toBe(false);
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("stops polling and surfaces error on failed run", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    vi.spyOn(api, "getProjectRun").mockReset();
    vi.spyOn(api, "getProjectRun")
      .mockResolvedValueOnce(makeRun("running") as unknown as RunResponse)
      .mockResolvedValue(
        makeRun("failed", {
          latest_error: { code: "ERR_001", message: "Step failed" },
        }) as unknown as RunResponse,
      );

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    // First poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    // Second poll — returns failed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(result.current.running).toBe(false);
    expect(result.current.lastRunError).toContain("ERR_001");
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("stops polling after consecutive errors", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    // All polls reject
    vi.spyOn(api, "getProjectRun").mockRejectedValue(
      new ApiError(0, { code: "SIDECAR_UNREACHABLE", message: "Down" }),
    );
    vi.spyOn(api, "getProjectRunSteps").mockRejectedValue(
      new ApiError(0, { code: "SIDECAR_UNREACHABLE", message: "Down" }),
    );

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    // 5 consecutive errors * 2000ms = 10000ms
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(result.current.running).toBe(false);
    expect(result.current.error).toContain("multiple retries");
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("detects a stalled run but keeps polling", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    // Always return running with same steps
    vi.spyOn(api, "getProjectRun").mockReset();
    vi.spyOn(api, "getProjectRun").mockResolvedValue(makeRun("running") as unknown as RunResponse);
    vi.spyOn(api, "getProjectRunSteps").mockReset();
    vi.spyOn(api, "getProjectRunSteps").mockResolvedValue(
      makeSteps(["running", "running", "running"]) as unknown as RunStepsResponse,
    );

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    // STALL_POLL_LIMIT = 30 polls * 2000ms = 60000ms
    for (let i = 0; i < 35; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
    }

    // Should still be running (keeps polling), but flagged as stalled
    expect(result.current.running).toBe(true);
    expect(result.current.runStalled).toBe(true);
    // Should NOT have called onRunComplete
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("stops watching an in-progress run", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.running).toBe(true);

    await act(async () => {
      result.current.stopWatchingRun();
    });

    expect(result.current.running).toBe(false);
    expect(result.current.error).toContain("Stopped watching");
  });

  it("health gate prevents run when sidecar is down", async () => {
    vi.spyOn(api, "health").mockRejectedValue(
      new ApiError(0, {
        code: "SIDECAR_UNREACHABLE",
        message: "Could not reach the Cardre sidecar.",
      }),
    );

    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.running).toBe(false);
    expect(result.current.error).toContain("SIDECAR_UNREACHABLE");
    expect(api.runPlan).not.toHaveBeenCalled();
  });

  it("unmounts cleanly without setState warnings", async () => {
    const onComplete = vi.fn();
    const { result, unmount } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    unmount();

    // After unmount, advancing timers should not trigger setState
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    // No error = pass
  });

  it("surfaces latest_error when status is 'interrupted' (treats like failed)", async () => {
    // RED: A run recovered as 'interrupted' must surface its latest_error
    // (RUN_RECOVERED_STALE) so the user sees the recovery. Currently
    // useRunProgress only sets lastRunError inside `if (run.status === "failed")`
    // (useRunProgress.ts:204), so 'interrupted' falls through with no error
    // surfaced despite the diagnostic being severity 'error'.
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    vi.spyOn(api, "getProjectRun").mockReset();
    vi.spyOn(api, "getProjectRun")
      .mockResolvedValueOnce(makeRun("running") as unknown as RunResponse)
      .mockResolvedValue(
        makeRun("interrupted", {
          latest_error: {
            code: "RUN_RECOVERED_STALE",
            message: "Run was stuck in 'running' — recovered as interrupted.",
          },
        }) as unknown as RunResponse,
      );

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    // First poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    // Second poll — returns interrupted
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(result.current.running).toBe(false);
    expect(result.current.lastRunError).toContain("RUN_RECOVERED_STALE");
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("renders all step errors on failure, not just the first", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    vi.spyOn(api, "getProjectRun").mockReset();
    vi.spyOn(api, "getProjectRun")
      .mockResolvedValueOnce(makeRun("running") as unknown as RunResponse)
      .mockResolvedValue(
        makeRun("failed", {
          latest_error: { code: "ERR_GLOBAL", message: "Global failure" },
        }) as unknown as RunResponse,
      );

    const stepsWithErrors = {
      run_id: RUN_ID,
      steps: [
        { run_step_id: "rs_0", step_id: "step_a", node_type: "test", status: "failed", started_at: "", input_artifact_ids: [], output_artifact_ids: [], warnings: [], is_carried_forward: false, errors: [{ code: "ERR_A", message: "Step A failed", traceback: "traceA" }] },
        { run_step_id: "rs_1", step_id: "step_b", node_type: "test", status: "failed", started_at: "", input_artifact_ids: [], output_artifact_ids: [], warnings: [], is_carried_forward: false, errors: [{ code: "ERR_B", message: "Step B failed", traceback: "traceB" }] },
      ],
    };
    vi.spyOn(api, "getProjectRunSteps").mockResolvedValue(stepsWithErrors as unknown as RunStepsResponse);

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });

    expect(result.current.running).toBe(false);
    // Both step errors must appear in lastRunError
    expect(result.current.lastRunError).toContain("ERR_A");
    expect(result.current.lastRunError).toContain("ERR_B");
  });

  it("distinguishes RUN_DISPATCH_FAILED from RUN_EXECUTION_FAILED in startRun", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    // runPlan throws RUN_DISPATCH_FAILED
    vi.spyOn(api, "runPlan").mockRejectedValue(
      new ApiError(500, {
        code: "RUN_DISPATCH_FAILED",
        message: "Failed to start background run thread",
      }),
    );

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.running).toBe(false);
    expect(result.current.error).toContain("RUN_DISPATCH_FAILED");
  });

  it("shows stale warning when is_stale is true even with a fresh heartbeat", async () => {
    // RED: The backend computes is_stale and returns it on RunResponse,
    // but useRunProgress never reads it. A run that is stale (heartbeat
    // old) but still status='running' should surface a stale warning
    // before the stall heuristic (60s no step change) fires.
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    const staleRun = makeRun("running", {
      is_stale: true,
      heartbeat_at: "2020-01-01T00:00:00Z",
    });
    vi.spyOn(api, "getProjectRun").mockReset();
    vi.spyOn(api, "getProjectRun").mockResolvedValue(staleRun as unknown as RunResponse);

    await act(async () => {
      result.current.startRun("pv1");
      await vi.advanceTimersByTimeAsync(0);
    });

    // First poll — returns running + is_stale: true
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    // The hook should surface staleness immediately via a diagnostic,
    // not wait for the 60s stall heuristic.
    const staleDiag = result.current.diagnostics.find((d) => d.toLowerCase().includes("stale"));
    expect(staleDiag, "is_stale=true should produce a stale diagnostic on first poll").toBeTruthy();
  });
});
