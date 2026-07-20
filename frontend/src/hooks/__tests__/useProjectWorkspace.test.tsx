import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { api } from "../../api/client";
import { useProjectWorkspace } from "../useProjectWorkspace";

const SAMPLE_RUNS = [
  {
    run_id: "r-2",
    plan_version_id: "v-other",
    status: "running",
    started_at: "2024-01-01T00:00:00",
  },
];

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  Wrapper.displayName = "QueryClientWrapper";
  return Wrapper;
}

describe("useProjectWorkspace", () => {
  const mockScoped = {
    listPlans: vi.fn().mockResolvedValue({ plans: [] }),
    createPlan: vi.fn(),
    listPlanVersions: vi.fn().mockResolvedValue({ versions: [] }),
    listRuns: vi.fn(),
    createRun: vi.fn(),
    getRun: vi.fn(),
    listRunSteps: vi.fn(),
    listRunEvidence: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(api, "getProject").mockResolvedValue({
      project_id: "p-1",
      name: "Test",
      cardre_version: "0.1.0",
      created_at: "",
    } as never);
    vi.spyOn(api, "forProject").mockReturnValue(
      mockScoped as unknown as ReturnType<typeof api.forProject>,
    );
  });

  it("shows empty visibleRuns when selected version has no runs", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: SAMPLE_RUNS });
    mockScoped.listPlans.mockResolvedValue({
      plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }],
    });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [
        {
          plan_version_id: "v-empty",
          plan_id: "pl-1",
          is_committed: true,
          version_number: 1,
          created_at: "",
        },
      ],
    });

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedPlanId).toBe("pl-1");
    });

    act(() => {
      result.current.setSelectedVersionId("v-empty");
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedVersionId).toBe("v-empty");
    });

    expect(result.current.visibleRuns).toEqual([]);
    expect(result.current.effectiveSelectedRunId).toBeNull();
  });

  it("selects a run from visible runs and loads details", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: SAMPLE_RUNS });
    mockScoped.listPlans.mockResolvedValue({
      plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }],
    });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [
        {
          plan_version_id: "v-other",
          plan_id: "pl-1",
          is_committed: true,
          version_number: 1,
          created_at: "",
        },
      ],
    });
    mockScoped.getRun.mockResolvedValue(SAMPLE_RUNS[0]);

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedPlanId).toBe("pl-1");
    });

    act(() => {
      result.current.setSelectedVersionId("v-other");
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedVersionId).toBe("v-other");
    });

    act(() => {
      result.current.setSelectedRunId("r-2");
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedRunId).toBe("r-2");
    });

    expect(mockScoped.getRun).toHaveBeenCalledWith("r-2");
  });

  it("polling refetches active run queries and stops at terminal", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: SAMPLE_RUNS });
    mockScoped.listPlans.mockResolvedValue({
      plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }],
    });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [
        {
          plan_version_id: "v-other",
          plan_id: "pl-1",
          is_committed: true,
          version_number: 1,
          created_at: "",
        },
      ],
    });
    const runningRun = {
      run_id: "r-2",
      plan_version_id: "v-other",
      status: "running",
      started_at: "2024-01-01T00:00:00",
    };
    const terminalRun = {
      run_id: "r-2",
      plan_version_id: "v-other",
      status: "succeeded",
      started_at: "2024-01-01T00:00:00",
      finished_at: "2024-01-01T00:01:00",
    };
    mockScoped.getRun.mockResolvedValueOnce(runningRun).mockResolvedValue(terminalRun);
    mockScoped.listRunSteps.mockResolvedValue([]);
    mockScoped.listRunEvidence.mockResolvedValue([]);

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedPlanId).toBe("pl-1");
    });

    act(() => {
      result.current.setSelectedVersionId("v-other");
    });
    await waitFor(() => {
      expect(result.current.effectiveSelectedVersionId).toBe("v-other");
    });

    act(() => {
      result.current.setSelectedRunId("r-2");
    });
    await waitFor(() => {
      expect(result.current.effectiveSelectedRunId).toBe("r-2");
    });

    await waitFor(() => {
      expect(mockScoped.getRun).toHaveBeenCalled();
    });

    const runsBefore = mockScoped.listRuns.mock.calls.length;
    const getRunBefore = mockScoped.getRun.mock.calls.length;
    const stepsBefore = mockScoped.listRunSteps.mock.calls.length;
    const evBefore = mockScoped.listRunEvidence.mock.calls.length;

    await waitFor(
      () => {
        expect(mockScoped.listRuns.mock.calls.length).toBeGreaterThan(runsBefore);
      },
      { timeout: 3_000, interval: 200 },
    );
    expect(mockScoped.getRun.mock.calls.length).toBeGreaterThan(getRunBefore);
    expect(mockScoped.listRunSteps.mock.calls.length).toBeGreaterThan(stepsBefore);
    expect(mockScoped.listRunEvidence.mock.calls.length).toBeGreaterThan(evBefore);

    const runsAfterTerminal = mockScoped.listRuns.mock.calls.length;
    const getRunAfterTerminal = mockScoped.getRun.mock.calls.length;
    const stepsAfterTerminal = mockScoped.listRunSteps.mock.calls.length;
    const evAfterTerminal = mockScoped.listRunEvidence.mock.calls.length;

    await waitFor(
      () => {
        expect(mockScoped.listRuns.mock.calls.length).toBe(runsAfterTerminal);
      },
      { timeout: 2_000, interval: 200 },
    );

    expect(mockScoped.getRun.mock.calls.length).toBe(getRunAfterTerminal);
    expect(mockScoped.listRunSteps.mock.calls.length).toBe(stepsAfterTerminal);
    expect(mockScoped.listRunEvidence.mock.calls.length).toBe(evAfterTerminal);
  });

  it("project selection never carries the typed creation path", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: [] });
    mockScoped.listPlans.mockResolvedValue({ plans: [] });

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-99" }), {
      wrapper: createWrapper(),
    });

    // The scope only contains projectId — no path field
    expect(result.current).toBeDefined();
    // We can verify by checking that the API call happens without an X-Project-Path header
    expect(api.forProject).toHaveBeenCalledWith({ projectId: "p-99" });
  });
});
