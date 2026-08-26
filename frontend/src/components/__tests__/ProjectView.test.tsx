import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { api } from "../../api/client";
import { ProjectView } from "../ProjectView";

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  Wrapper.displayName = "QueryClientWrapper";
  return Wrapper;
}

describe("ProjectView", () => {
  const mockScoped = {
    listPlans: vi.fn().mockResolvedValue({ plans: [] }),
    createPlan: vi.fn(),
    createCanonicalVersion: vi.fn(),
    getPlanVersionSteps: vi.fn().mockResolvedValue([]),
    updateStepParams: vi.fn(),
    commitPlanVersion: vi.fn(),
    listPlanVersions: vi.fn().mockResolvedValue({ versions: [] }),
    listRuns: vi.fn().mockResolvedValue({ runs: [] }),
    createRun: vi.fn(),
    getRun: vi.fn(),
    listRunSteps: vi.fn(),
    listRunEvidence: vi.fn(),
    cancelRun: vi.fn(),
    listReports: vi.fn().mockResolvedValue({ reports: [] }),
    listExports: vi.fn().mockResolvedValue({ exports: [] }),
    listNodeTypes: vi.fn().mockResolvedValue({ node_types: [] }),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(api, "getProject").mockResolvedValue({
      project_id: "p-1",
      name: "Test Project",
      cardre_version: "0.1.0",
      created_at: "",
    } as never);
    vi.spyOn(api, "forProject").mockReturnValue(
      mockScoped as unknown as ReturnType<typeof api.forProject>,
    );
  });

  it("renders project name and back button", async () => {
    render(<ProjectView projectId="p-1" onBack={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Test Project")).toBeDefined();
    });

    expect(screen.getByText("Back")).toBeDefined();
    expect(screen.getByText("p-1")).toBeDefined();
  });

  it("renders plan sidebar and version panel", async () => {
    render(<ProjectView projectId="p-1" onBack={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Plans")).toBeDefined();
    });

    expect(screen.getByText("Runs")).toBeDefined();
    expect(screen.getByText("Plan Versions")).toBeDefined();
    expect(screen.getByText("Run Details")).toBeDefined();
  });

  it("renders the launch-pathway generator when a plan has no versions", async () => {
    mockScoped.listPlans.mockResolvedValue({
      plans: [{ plan_id: "pl-1", name: "Plan", project_id: "p-1", created_at: "" }],
    });

    render(<ProjectView projectId="p-1" onBack={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getAllByText("Generate launch pathway").length).toBeGreaterThan(0);
    });

    expect(screen.getByPlaceholderText("Absolute path to your Parquet file")).toBeDefined();
  });

  it("renders error banner when present", async () => {
    mockScoped.listPlans.mockRejectedValue(new Error("API error"));

    render(<ProjectView projectId="p-1" onBack={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/API error/)).toBeDefined();
    });
  });
});
