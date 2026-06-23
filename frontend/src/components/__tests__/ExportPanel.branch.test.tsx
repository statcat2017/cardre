import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ExportPanel } from "../ExportPanel";

function createClientWithCache(entries: Array<[Array<string | number>, unknown]>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 300_000 } },
  });
  for (const [key, data] of entries) {
    client.setQueryData(key, data);
  }
  return client;
}

const branches = [
  { branch_id: "br_default", name: "Baseline", branch_type: "baseline", status: "active", plan_id: "plan1", base_plan_version_id: "pv1", head_plan_version_id: "pv1" },
  { branch_id: "br_challenger", name: "Challenger", branch_type: "challenger", status: "active", plan_id: "plan1", base_plan_version_id: "pv1", head_plan_version_id: "pv1" },
];

export function setupFetchStub(readinessCalls: string[]) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn((url: string | URL | Request, opts?: RequestInit) => {
    const urlStr = typeof url === "string" ? url : url.toString();
    if (urlStr.includes("/report-readiness")) {
      const body = JSON.parse(opts?.body as string);
      readinessCalls.push(body.target_branch_id);
      return Promise.resolve(new Response(
        JSON.stringify({ ready: true, status: "ready", blockers: [], warnings: [] }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ));
    }
    if (urlStr.includes("/reports")) {
      return Promise.resolve(new Response(
        JSON.stringify([]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ));
    }
    return originalFetch(url, opts);
  }) as typeof fetch;
  return () => { globalThis.fetch = originalFetch; };
}

describe("ExportPanel branch selection", () => {
  it("calls onBranchSelect when controlled select changes", async () => {
    const client = createClientWithCache([
      [["projectBranches", "prj1"], { branches }],
    ]);

    const onBranchSelect = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <ExportPanel
          projectId="prj1"
          targetBranchId="br_default"
          onBranchSelect={onBranchSelect}
        />
      </QueryClientProvider>,
    );

    const select = await screen.findByTestId("branch-select");
    await userEvent.selectOptions(select, "br_challenger");

    expect(onBranchSelect).toHaveBeenCalledWith("br_challenger");
  });

  it("renders read-only branch text when onBranchSelect is absent", async () => {
    const client = createClientWithCache([
      [["projectBranches", "prj1"], { branches }],
    ]);

    render(
      <QueryClientProvider client={client}>
        <ExportPanel
          projectId="prj1"
          targetBranchId="br_default"
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Baseline")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("branch-select")).not.toBeInTheDocument();
  });

  it('shows "Select a branch." when targetBranchId is null', async () => {
    const client = createClientWithCache([]);
    render(
      <QueryClientProvider client={client}>
        <ExportPanel projectId="prj1" targetBranchId={null} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Select a branch.").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows no-run fallback when there are no successful runs", async () => {
    const client = createClientWithCache([]);
    render(
      <QueryClientProvider client={client}>
        <ExportPanel projectId="prj1" targetBranchId="br_default" />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Run the Scorecard Pathway/)).toBeInTheDocument();
    });
  });

  it("shows no recheck button when no branch is selected", async () => {
    const client = createClientWithCache([]);
    render(
      <QueryClientProvider client={client}>
        <ExportPanel projectId="prj1" targetBranchId={null} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /re-check/i })).not.toBeInTheDocument();
    });
  });

  it("triggers readiness for current branch", async () => {
    const readinessCalls: string[] = [];
    const restore = setupFetchStub(readinessCalls);
    const run = { run_id: "run1", plan_version_id: "pv1", status: "succeeded", started_at: "2026-02-01T00:00:00Z", finished_at: "2026-02-01T01:00:00Z", step_count: 10 };

    const client = createClientWithCache([
      [["projectBranches", "prj1"], { branches }],
      [["projectRuns", "prj1"], { runs: [run] }],
    ]);

    render(
      <QueryClientProvider client={client}>
        <ExportPanel projectId="prj1" targetBranchId="br_default" />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(readinessCalls).toContain("br_default");
    });

    restore();
  });

  it("re-fetches readiness when targetBranchId prop changes", async () => {
    const readinessCalls: string[] = [];
    const restore = setupFetchStub(readinessCalls);
    const run = { run_id: "run1", plan_version_id: "pv1", status: "succeeded", started_at: "2026-02-01T00:00:00Z", finished_at: "2026-02-01T01:00:00Z", step_count: 10 };

    const initialClient = createClientWithCache([
      [["projectBranches", "prj1"], { branches }],
      [["projectRuns", "prj1"], { runs: [run] }],
    ]);

    const { rerender } = render(
      <QueryClientProvider client={initialClient}>
        <ExportPanel projectId="prj1" targetBranchId="br_default" />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(readinessCalls).toContain("br_default");
    });

    const newClient = createClientWithCache([
      [["projectBranches", "prj1"], { branches }],
      [["projectRuns", "prj1"], { runs: [run] }],
    ]);

    rerender(
      <QueryClientProvider client={newClient}>
        <ExportPanel projectId="prj1" targetBranchId="br_challenger" />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(readinessCalls).toContain("br_challenger");
    });

    restore();
  });
});
