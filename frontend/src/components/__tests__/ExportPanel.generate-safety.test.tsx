import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { ExportPanel } from "../ExportPanel";
import type { BranchListItem } from "../../types";

const BASE = "http://127.0.0.1:8752";

const branches: BranchListItem[] = [
  {
    branch_id: "br_default",
    name: "Baseline",
    branch_type: "baseline",
    status: "active",
    plan_id: "plan1",
    base_plan_version_id: "pv1",
    head_plan_version_id: "pv1",
  },
  {
    branch_id: "br_challenger",
    name: "Challenger",
    branch_type: "challenger",
    status: "active",
    plan_id: "plan1",
    base_plan_version_id: "pv1",
    head_plan_version_id: "pv1",
  },
];

const run = {
  run_id: "run1",
  plan_version_id: "pv1",
  status: "succeeded",
  started_at: "2026-02-01T00:00:00Z",
  finished_at: "2026-02-01T01:00:00Z",
  step_count: 10,
};

function renderExportPanel(targetBranchId: string | null, onBranchSelect?: (id: string) => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 300_000 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ExportPanel
        projectId="prj1"
        targetBranchId={targetBranchId}
        onBranchSelect={onBranchSelect}
      />
    </QueryClientProvider>,
  );
}

describe("ExportPanel generate safety", () => {
  it("enables generate with ready readiness and clicking calls the right branch/run", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    let capturedUrl: string | null = null;

    server.use(
      http.get(`${BASE}/projects/:projectId/branches`, () => HttpResponse.json({ branches })),
      http.get(`${BASE}/projects/:projectId/runs`, () => HttpResponse.json({ runs: [run] })),
      http.post(`${BASE}/projects/:projectId/runs/:runId/report-readiness`, () =>
        HttpResponse.json({ ready: true, status: "ready", blockers: [], warnings: [] }),
      ),
      http.get(`${BASE}/projects/:projectId/runs/:runId/reports`, () => HttpResponse.json([])),
      http.post(`${BASE}/projects/:projectId/runs/:runId/reports`, async ({ request }) => {
        capturedUrl = request.url;
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            report_id: "rpt1",
            status: "completed",
            report_bundle_path: "/rpt.json",
            html_path: "/rpt.html",
            export_path: "/rpt.zip",
            zip_path: "/rpt.zip",
          },
          { status: 201 },
        );
      }),
    );

    renderExportPanel("br_default");

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /generate audit pack/i });
      expect(btn).toBeEnabled();
    });

    await userEvent.click(screen.getByRole("button", { name: /generate audit pack/i }));

    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
      expect(capturedBody!.target_branch_id).toBe("br_default");
      expect(capturedBody!.report_mode).toBe("branch");
    });
    expect(capturedUrl).toContain("/runs/run1/reports");
  });

  it("disables generate and shows Checking during branch-switch refetch (no stale state leak)", async () => {
    server.use(
      http.get(`${BASE}/projects/:projectId/branches`, () => HttpResponse.json({ branches })),
      http.get(`${BASE}/projects/:projectId/runs`, () => HttpResponse.json({ runs: [run] })),
      http.post(`${BASE}/projects/:projectId/runs/:runId/report-readiness`, async ({ request }) => {
        const url = new URL(request.url);
        const targetBranch = url.pathname.includes("br_default") ? "br_default" : "br_challenger";
        return HttpResponse.json({
          ready: true,
          status: "ready",
          blockers: [],
          warnings: [],
          _echo_branch: targetBranch,
        });
      }),
      http.get(`${BASE}/projects/:projectId/runs/:runId/reports`, () => HttpResponse.json([])),
    );

    const { rerender } = renderExportPanel("br_default");

    // Wait for first readiness to resolve and generate to enable
    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /generate audit pack/i });
      expect(btn).toBeEnabled();
    });

    // Switch branch — triggers refetch
    rerender(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 300_000 } } })
        }
      >
        <ExportPanel projectId="prj1" targetBranchId="br_challenger" />
      </QueryClientProvider>,
    );

    // During the refetch, generate should be disabled
    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /generate audit pack/i });
      expect(btn).toBeDisabled();
    });

    // "Checking readiness…" should be shown, not stale "Ready."
    expect(screen.getByText("Checking readiness…")).toBeInTheDocument();
  });

  it("disables generate on readiness error", async () => {
    server.use(
      http.get(`${BASE}/projects/:projectId/branches`, () => HttpResponse.json({ branches })),
      http.get(`${BASE}/projects/:projectId/runs`, () => HttpResponse.json({ runs: [run] })),
      http.post(`${BASE}/projects/:projectId/runs/:runId/report-readiness`, () =>
        HttpResponse.text("Internal error", { status: 500 }),
      ),
      http.get(`${BASE}/projects/:projectId/runs/:runId/reports`, () => HttpResponse.json([])),
    );

    renderExportPanel("br_default");

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /generate audit pack/i });
      expect(btn).toBeDisabled();
    });
  });

  it("shows generate error when generate endpoint fails", async () => {
    server.use(
      http.get(`${BASE}/projects/:projectId/branches`, () => HttpResponse.json({ branches })),
      http.get(`${BASE}/projects/:projectId/runs`, () => HttpResponse.json({ runs: [run] })),
      http.post(`${BASE}/projects/:projectId/runs/:runId/report-readiness`, () =>
        HttpResponse.json({ ready: true, status: "ready", blockers: [], warnings: [] }),
      ),
      http.get(`${BASE}/projects/:projectId/runs/:runId/reports`, () => HttpResponse.json([])),
      http.post(`${BASE}/projects/:projectId/runs/:runId/reports`, () =>
        HttpResponse.json(
          { detail: { code: "GENERATE_FAILED", message: "Bundle assembly failed" } },
          { status: 500 },
        ),
      ),
    );

    renderExportPanel("br_default");

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /generate audit pack/i });
      expect(btn).toBeEnabled();
    });

    await userEvent.click(screen.getByRole("button", { name: /generate audit pack/i }));

    await waitFor(() => {
      expect(screen.getByText(/Report generation failed/)).toBeInTheDocument();
    });

    expect(screen.getByText(/Bundle assembly failed/)).toBeInTheDocument();
  });
});
