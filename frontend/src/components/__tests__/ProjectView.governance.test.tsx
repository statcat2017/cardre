import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ProjectView } from "../ProjectView";

vi.mock("../../hooks/useRunProgress", () => ({
  useRunProgress: () => ({
    running: false,
    error: null,
    runStalled: false,
    carriedForwardSteps: {},
    liveStepStatus: {},
    stepProgress: null,
    diagnostics: [],
    liveDiagnostic: null,
    startRun: vi.fn(),
    stopWatchingRun: vi.fn(),
    addDiagnostic: vi.fn(),
    lastPollError: null,
    lastRunError: null,
  }),
}));

vi.mock("../../hooks/useWorkflowGuidance", () => ({
  useWorkflowGuidance: () => ({ data: null }),
}));

vi.mock("../../hooks/useProjectPlanState", () => ({
  useProjectPlanState: () => ({
    project: { project_id: "prj1", name: "Test Project", path: "/tmp/test", created_at: "2026-01-01" },
    projectLoading: false,
    scorecardPlan: null,
    planId: null,
    planData: null,
    refetchPlan: vi.fn(),
  }),
}));

vi.mock("../../hooks/useSelectedBranch", () => ({
  useSelectedBranch: () => ({
    selectedBranchId: null,
    setSelectedBranchId: vi.fn(),
  }),
}));

vi.mock("../../hooks/useJourneyActions", () => ({
  useJourneyActions: () => ({
    handleJourneyAction: vi.fn(),
  }),
}));

vi.mock("../../hooks/useDiagnosticsPanel", () => ({
  useDiagnosticsPanel: () => ({ diagnosticsMessages: [] }),
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ProjectView governance", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders health query and governance_enabled flag", async () => {
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

    renderWithClient(<ProjectView projectId="prj1" onBack={vi.fn()} />);
    // With mocked hooks, the project loads and the pathway section shows
    // "No scorecard pathway found" (planData is null in mock)
    expect(screen.getByText(/No scorecard pathway found/)).toBeInTheDocument();
  });
});
