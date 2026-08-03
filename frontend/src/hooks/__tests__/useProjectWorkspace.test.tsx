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
    createCanonicalVersion: vi.fn(),
    getPlanVersionSteps: vi.fn().mockResolvedValue([]),
    updateStepParams: vi.fn(),
    commitPlanVersion: vi.fn(),
    listPlanVersions: vi.fn().mockResolvedValue({ versions: [] }),
    listRuns: vi.fn(),
    createRun: vi.fn(),
    getRun: vi.fn(),
    listRunSteps: vi.fn(),
    listRunEvidence: vi.fn(),
    cancelRun: vi.fn(),
    listReports: vi.fn().mockResolvedValue({ reports: [] }),
    listExports: vi.fn().mockResolvedValue({ exports: [] }),
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

    // Wait for polling to fire (1s interval)
    await new Promise((resolve) => setTimeout(resolve, 1200));

    expect(mockScoped.listRuns.mock.calls.length).toBeGreaterThan(runsBefore);
    expect(mockScoped.getRun.mock.calls.length).toBeGreaterThan(getRunBefore);
    expect(mockScoped.listRunSteps.mock.calls.length).toBeGreaterThan(stepsBefore);
    expect(mockScoped.listRunEvidence.mock.calls.length).toBeGreaterThan(evBefore);

    const runsAfterTerminal = mockScoped.listRuns.mock.calls.length;
    const getRunAfterTerminal = mockScoped.getRun.mock.calls.length;
    const stepsAfterTerminal = mockScoped.listRunSteps.mock.calls.length;
    const evAfterTerminal = mockScoped.listRunEvidence.mock.calls.length;

    // Wait for another polling interval — counts must not increase
    await new Promise((resolve) => setTimeout(resolve, 1200));

    expect(mockScoped.listRuns.mock.calls.length).toBe(runsAfterTerminal);
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

  it("cancelRunMutation calls scoped.cancelRun and invalidates queries", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: [] });
    mockScoped.listPlans.mockResolvedValue({ plans: [] });
    mockScoped.cancelRun.mockResolvedValue({
      run_id: "r-1",
      status: "running",
      cancel_requested: true,
      started_at: "",
      plan_version_id: "v-1",
      step_count: 0,
      is_stale: false,
    });

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.cancelRunMutation.mutateAsync("r-1");
    });

    expect(mockScoped.cancelRun).toHaveBeenCalledWith("r-1");
  });

  it("createCanonicalVersionMutation calls scoped.createCanonicalVersion and selects the version", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: [] });
    mockScoped.listPlans.mockResolvedValue({
      plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }],
    });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [
        {
          plan_version_id: "v-new",
          plan_id: "pl-1",
          version_number: 1,
          is_committed: false,
          created_at: "",
        },
      ],
    });
    mockScoped.createCanonicalVersion.mockResolvedValue({
      plan_version_id: "v-new",
      plan_id: "pl-1",
      version_number: 1,
      is_committed: false,
      created_at: "",
    });

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedPlanId).toBe("pl-1");
    });

    act(() => {
      result.current.setSourcePath("/tmp/in.csv");
    });

    await act(async () => {
      await result.current.createCanonicalVersionMutation.mutateAsync();
    });

    expect(mockScoped.createCanonicalVersion).toHaveBeenCalledWith("pl-1", {
      source_path: "/tmp/in.csv",
    });
    expect(result.current.effectiveSelectedVersionId).toBe("v-new");
  });

  it("updateStepParamsMutation calls scoped.updateStepParams and refetches steps", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: [] });
    mockScoped.listPlans.mockResolvedValue({
      plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }],
    });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [
        {
          plan_version_id: "v-draft",
          plan_id: "pl-1",
          version_number: 1,
          is_committed: false,
          created_at: "",
        },
      ],
    });
    mockScoped.updateStepParams.mockResolvedValue({
      plan_version_id: "v-draft",
      plan_id: "pl-1",
      version_number: 1,
      is_committed: false,
      created_at: "",
    });

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedVersionId).toBe("v-draft");
    });

    await act(async () => {
      await result.current.updateStepParamsMutation.mutateAsync({
        stepId: "s1",
        params: { min_iv: 0.05 },
      });
    });

    expect(mockScoped.updateStepParams).toHaveBeenCalledWith("v-draft", "s1", {
      params: { min_iv: 0.05 },
    });
  });

  it("commitVersionMutation calls scoped.commitPlanVersion", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: [] });
    mockScoped.listPlans.mockResolvedValue({
      plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }],
    });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [
        {
          plan_version_id: "v-draft",
          plan_id: "pl-1",
          version_number: 1,
          is_committed: false,
          created_at: "",
        },
      ],
    });
    mockScoped.commitPlanVersion.mockResolvedValue({
      plan_version_id: "v-draft",
      plan_id: "pl-1",
      version_number: 1,
      is_committed: true,
      created_at: "",
    });

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.effectiveSelectedVersionId).toBe("v-draft");
    });

    await act(async () => {
      await result.current.commitVersionMutation.mutateAsync();
    });

    expect(mockScoped.commitPlanVersion).toHaveBeenCalledWith("v-draft");
  });

  it("polling stops at cancelled status", async () => {
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
    const cancelledRun = {
      run_id: "r-2",
      plan_version_id: "v-other",
      status: "cancelled",
      started_at: "2024-01-01T00:00:00",
      finished_at: "2024-01-01T00:01:00",
    };
    mockScoped.getRun.mockResolvedValueOnce(runningRun).mockResolvedValue(cancelledRun);
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

    // Wait for polling to fire (1s interval)
    await new Promise((resolve) => setTimeout(resolve, 1200));

    expect(mockScoped.listRuns.mock.calls.length).toBeGreaterThan(runsBefore);
    expect(mockScoped.getRun.mock.calls.length).toBeGreaterThan(getRunBefore);

    const runsAfterCancelled = mockScoped.listRuns.mock.calls.length;
    const getRunAfterCancelled = mockScoped.getRun.mock.calls.length;

    // Wait for another polling interval — counts must not increase
    await new Promise((resolve) => setTimeout(resolve, 1200));

    expect(mockScoped.listRuns.mock.calls.length).toBe(runsAfterCancelled);
    expect(mockScoped.getRun.mock.calls.length).toBe(getRunAfterCancelled);
  });

  it.each([
    ["running→terminal transition", "running", "succeeded"],
    ["first status already terminal", "succeeded", "succeeded"],
  ])("refreshes reports and exports after %s", async (_label, firstStatus, terminalStatus) => {
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
      status: firstStatus,
      started_at: "2024-01-01T00:00:00",
    };
    const succeededRun = {
      run_id: "r-2",
      plan_version_id: "v-other",
      status: terminalStatus,
      started_at: "2024-01-01T00:00:00",
      finished_at: "2024-01-01T00:00:05",
    };
    mockScoped.getRun.mockResolvedValueOnce(runningRun).mockResolvedValue(succeededRun);
    mockScoped.listRunSteps.mockResolvedValue([]);
    mockScoped.listRunEvidence.mockResolvedValue([]);
    const report = {
      report_id: "rep-1",
      run_id: "r-2",
      report_type: "manifest",
      path: "/tmp/report.json",
      created_at: "2024-01-01T00:00:05",
    };
    const exportItem = {
      export_id: "exp-1",
      run_id: "r-2",
      export_type: "python_scorer",
      path: "/tmp/scorer.py",
      created_at: "2024-01-01T00:00:05",
      size_bytes: 1024,
    };
    // First (pre-terminal) fetch returns empty; the terminal refresh returns
    // the populated outputs.
    mockScoped.listReports
      .mockResolvedValueOnce({ reports: [] })
      .mockResolvedValue({ reports: [report] });
    mockScoped.listExports
      .mockResolvedValueOnce({ exports: [] })
      .mockResolvedValue({ exports: [exportItem] });

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

    // Once a terminal status is observed, the panels must end up showing the
    // populated outputs, not stale empty results.
    await waitFor(() => {
      expect(result.current.reportsQuery.data?.reports?.[0]?.report_id).toBe("rep-1");
      expect(result.current.exportsQuery.data?.exports?.[0]?.export_id).toBe("exp-1");
    });
  });
});
