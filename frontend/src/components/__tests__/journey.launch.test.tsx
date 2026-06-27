import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { ProjectView } from "../ProjectView";
import {
  PROJECT_ID,
  BRANCH_ID,
  RUN_ID,
  buildSucceededRun,
  buildWorkflowGuidanceManualBinningPhase,
  buildWorkflowGuidanceExportPhase,
  buildReportReadinessBlocked,
  buildReportReadinessReady,
  buildGenerateReportResponse,
} from "../../test/fixtures/launchJourney";

const BASE = "http://127.0.0.1:8752";

function renderProjectView() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectView projectId={PROJECT_ID} onBack={() => {}} />
    </QueryClientProvider>,
  );
}

describe("Guided launch journey", () => {
  it("loads guided project journey and shows pathway readiness", async () => {
    renderProjectView();

    await waitFor(() => {
      expect(screen.getByText("Test Project")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("Configure target")).toBeInTheDocument();
    });

    expect(screen.getByText("build")).toBeInTheDocument();
  });

  it("report blocker Go to step selects the blocked step and switches to pathway", async () => {
    const run = buildSucceededRun();
    const guidance = buildWorkflowGuidanceExportPhase();
    const blockerStepId = "target-definition";

    server.use(
      http.get(`${BASE}/plans/:planId/workflow-guidance`, () =>
        HttpResponse.json(guidance)
      ),
      http.get(`${BASE}/projects/:projectId/runs`, () =>
        HttpResponse.json({ runs: [run] })
      ),
      http.post(`${BASE}/projects/:projectId/runs/:runId/report-readiness`, () =>
        HttpResponse.json(buildReportReadinessBlocked(blockerStepId))
      ),
      http.get(`${BASE}/projects/:projectId/runs/:runId/reports`, () =>
        HttpResponse.json([])
      ),
    );

    renderProjectView();

    await waitFor(() => {
      expect(screen.getByText("Export audit pack")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("Export audit pack"));

    await waitFor(() => {
      expect(screen.getByText("Blocked")).toBeInTheDocument();
    });

    const goToStep = screen.getByRole("button", { name: /go to step/i });

    await userEvent.click(goToStep);

    await waitFor(() => {
      expect(screen.queryByText("Audit Pack Export")).not.toBeInTheDocument();
    });

    // Verify the blocker's step_id appears in the pathway/step inspector
    await waitFor(() => {
      const elements = screen.getAllByText(blockerStepId);
      expect(elements.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("ready report enables generate and calls generate with the right branch and run", async () => {
    const run = buildSucceededRun();
    const guidance = buildWorkflowGuidanceExportPhase();

    let capturedGenerateUrl: string | null = null;
    let capturedGenerateBody: Record<string, unknown> | null = null;

    server.use(
      http.get(`${BASE}/plans/:planId/workflow-guidance`, () =>
        HttpResponse.json(guidance)
      ),
      http.get(`${BASE}/projects/:projectId/runs`, () =>
        HttpResponse.json({ runs: [run] })
      ),
      http.post(`${BASE}/projects/:projectId/runs/:runId/report-readiness`, () =>
        HttpResponse.json(buildReportReadinessReady())
      ),
      http.get(`${BASE}/projects/:projectId/runs/:runId/reports`, () =>
        HttpResponse.json([])
      ),
      http.post(`${BASE}/projects/:projectId/runs/:runId/reports`, async ({ request }) => {
        capturedGenerateUrl = request.url;
        capturedGenerateBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json(buildGenerateReportResponse(), { status: 201 });
      }),
    );

    renderProjectView();

    await waitFor(() => {
      expect(screen.getByText("Export audit pack")).toBeInTheDocument();
    });
    await userEvent.click(screen.getByText("Export audit pack"));

    await waitFor(() => {
      const generateBtn = screen.getByRole("button", { name: /generate audit pack/i });
      expect(generateBtn).toBeEnabled();
    });

    await userEvent.click(screen.getByRole("button", { name: /generate audit pack/i }));

    await waitFor(() => {
      expect(capturedGenerateBody).not.toBeNull();
      expect(capturedGenerateBody!.target_branch_id).toBe(BRANCH_ID);
      expect(capturedGenerateBody!.report_mode).toBe("branch");
    });

    expect(capturedGenerateUrl).toContain(`/runs/${RUN_ID}/reports`);
  });

  it("manual-binning review gate: CTA selects manual-binning step and switches to editing", async () => {
    const guidance = buildWorkflowGuidanceManualBinningPhase();

    server.use(
      http.get(`http://127.0.0.1:8752/plans/:planId/workflow-guidance`, () =>
        HttpResponse.json(guidance)
      ),
      http.get(`http://127.0.0.1:8752/plans/:planId/steps/:stepId/editor-state`, () =>
        HttpResponse.json({ step_id: "manual-binning", method: "default", overrides: [], variables: [], selected_variable: null, source_info: null, variable_summaries: [], has_unsaved_changes: false, node_version: "1" })
      ),
    );

    renderProjectView();

    await waitFor(() => {
      expect(screen.getByText("Test Project")).toBeInTheDocument();
    });

    // CTA shows the manual-binning next action
    await waitFor(() => {
      expect(screen.getByText("Edit bins")).toBeInTheDocument();
    });

    // PathwayView is rendering (not in editing mode yet)
    expect(screen.queryByTestId("manual-binning-editor")).not.toBeInTheDocument();

    // Click CTA — triggers edit_bins journey action
    await userEvent.click(screen.getByText("Edit bins"));

    // After click, ProjectView sets editingStepId and switches to pathway.
    // ManualBinningEditor should render (identified by testid or its heading).
    await waitFor(() => {
      // The editor renders for the manual-binning step
      expect(screen.getByText(/Manual Binning/i)).toBeInTheDocument();
    });
  });
});
