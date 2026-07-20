import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { api } from "../../api/client";
import { useProjectWorkspace } from "../useProjectWorkspace";

const SAMPLE_RUNS = [
  { run_id: "r-1", plan_version_id: "v-empty", status: "succeeded", started_at: "2024-01-01T00:00:00" },
  { run_id: "r-2", plan_version_id: "v-other", status: "running", started_at: "2024-01-01T00:00:00" },
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
    vi.spyOn(api, "getProject").mockResolvedValue({ project_id: "p-1", name: "Test", cardre_version: "0.1.0", created_at: "", root: "" });
    vi.spyOn(api, "forProject").mockReturnValue(mockScoped as unknown as ReturnType<typeof api.forProject>);
  });

  it("shows empty visibleRuns when selected version has no runs", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: SAMPLE_RUNS });
    mockScoped.listPlans.mockResolvedValue({ plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }] });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [{ plan_version_id: "v-empty", plan_id: "pl-1", is_committed: true, version_number: 1, created_at: "" }],
    });

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.effectiveSelectedPlanId).toBe("pl-1");
    });

    act(() => { result.current.setSelectedVersionId("v-empty"); });

    await waitFor(() => {
      expect(result.current.effectiveSelectedVersionId).toBe("v-empty");
    });

    expect(result.current.visibleRuns).toEqual([]);
    expect(result.current.effectiveSelectedRunId).toBeNull();
  });

  it("selects a run from visible runs and loads details", async () => {
    mockScoped.listRuns.mockResolvedValue({ runs: SAMPLE_RUNS });
    mockScoped.listPlans.mockResolvedValue({ plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }] });
    mockScoped.listPlanVersions.mockResolvedValue({
      versions: [{ plan_version_id: "v-other", plan_id: "pl-1", is_committed: true, version_number: 1, created_at: "" }],
    });
    mockScoped.getRun.mockResolvedValue(SAMPLE_RUNS[1]);

    const { result } = renderHook(() => useProjectWorkspace({ projectId: "p-1" }), { wrapper: createWrapper() });

    await waitFor(() => {
      expect(result.current.effectiveSelectedPlanId).toBe("pl-1");
    });

    act(() => { result.current.setSelectedVersionId("v-other"); });

    await waitFor(() => {
      expect(result.current.effectiveSelectedVersionId).toBe("v-other");
    });

    act(() => { result.current.setSelectedRunId("r-2"); });

    await waitFor(() => {
      expect(result.current.effectiveSelectedRunId).toBe("r-2");
    });

    expect(mockScoped.getRun).toHaveBeenCalledWith("r-2");
  });
});
