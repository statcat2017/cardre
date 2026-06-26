import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { useRunProgress } from "../useRunProgress";
import type { ReactNode } from "react";

const PROJECT_ID = "prj_test";
const RUN_ID = "run_abc123";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
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
  vi.spyOn(api, "health").mockResolvedValue({ status: "ok", cardre_version: "0.1.0", registry_accessible: false, registered_node_count: 0, launch_node_count: 0, deferred_node_count: 0, governance_enabled: false, checked_at: "", diagnostics: [] });
  vi.spyOn(api, "runPlan").mockResolvedValue(makeRun("running") as any);
  vi.spyOn(api, "getRun").mockResolvedValue(makeRun("running") as any);
  vi.spyOn(api, "getRunSteps").mockResolvedValue(makeSteps(["running", "running", "running"]) as any);
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

    expect(api.getRun).toHaveBeenCalledTimes(1);
    expect(api.getRunSteps).toHaveBeenCalledTimes(1);

    // Second poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(api.getRun).toHaveBeenCalledTimes(2);
  });

  it("stops polling when run completes with succeeded status", async () => {
    const onComplete = vi.fn();
    const { result } = renderHook(() => useRunProgress(PROJECT_ID, onComplete), {
      wrapper: createWrapper(),
    });

    // First poll returns running, second returns succeeded
    vi.spyOn(api, "getRun").mockReset();
    vi.spyOn(api, "getRun")
      .mockResolvedValueOnce(makeRun("running") as any)
      .mockResolvedValue(makeRun("succeeded") as any);

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

    vi.spyOn(api, "getRun").mockReset();
    vi.spyOn(api, "getRun")
      .mockResolvedValueOnce(makeRun("running") as any)
      .mockResolvedValue(
        makeRun("failed", { latest_error: { code: "ERR_001", message: "Step failed" } }) as any,
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
    vi.spyOn(api, "getRun").mockRejectedValue(
      new ApiError(0, { code: "SIDECAR_UNREACHABLE", message: "Down" }),
    );
    vi.spyOn(api, "getRunSteps").mockRejectedValue(
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
    vi.spyOn(api, "getRun").mockReset();
    vi.spyOn(api, "getRun").mockResolvedValue(makeRun("running") as any);
    vi.spyOn(api, "getRunSteps").mockReset();
    vi.spyOn(api, "getRunSteps").mockResolvedValue(makeSteps(["running", "running", "running"]) as any);

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
      new ApiError(0, { code: "SIDECAR_UNREACHABLE", message: "Could not reach the Cardre sidecar." }),
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
});
