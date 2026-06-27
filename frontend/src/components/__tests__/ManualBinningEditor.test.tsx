import { describe, it, expect, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { ManualBinningEditor } from "../ManualBinningEditor";
import {
  buildManualBinningEditorState,
  buildReviewedEditorState,
} from "../../test/fixtures/manualBinning";

const BASE = "http://127.0.0.1:8752";

function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("ManualBinningEditor", () => {
  afterEach(() => server.resetHandlers());

  it("renders the two-column layout", async () => {
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () =>
        HttpResponse.json(buildManualBinningEditorState()),
      ),
    );
    renderWithQuery(
      <ManualBinningEditor
        planId="plan1"
        projectId="prj1"
        basePlanVersionId="pv1"
        onBack={() => {}}
        onPlanRefreshed={() => {}}
      />,
    );

    await waitFor(() => expect(screen.getByText("Manual Bin Editing")).toBeTruthy());
    // Left column: variable names (appear in both left and right panels)
    expect(screen.getAllByText("income").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("age").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("loan_amount").length).toBeGreaterThanOrEqual(1);
    // Right column: review actions
    expect(screen.getByText("Bin Review")).toBeTruthy();
    // Summary line
    expect(screen.getAllByText(/3 variables/).length).toBeGreaterThanOrEqual(1);
  });

  it("selecting a variable updates the detail panel", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () =>
        HttpResponse.json(buildManualBinningEditorState()),
      ),
    );
    renderWithQuery(
      <ManualBinningEditor
        planId="plan1"
        projectId="prj1"
        basePlanVersionId="pv1"
        onBack={() => {}}
        onPlanRefreshed={() => {}}
      />,
    );

    await waitFor(() => expect(screen.getAllByText("income").length).toBeGreaterThanOrEqual(1));
    // Click "age" in the left column — pick first match
    await user.click(screen.getAllByText("age")[0]);
    // The review panel should now show age's info
    await waitFor(() => expect(screen.getByText("non_monotonic")).toBeTruthy());
  });

  it("shows read-only reviewed state when review_status is reviewed", async () => {
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () =>
        HttpResponse.json(buildReviewedEditorState()),
      ),
    );
    renderWithQuery(
      <ManualBinningEditor
        planId="plan1"
        projectId="prj1"
        basePlanVersionId="pv1"
        onBack={() => {}}
        onPlanRefreshed={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Review complete")).toBeTruthy();
      expect(screen.getByText(/alice/)).toBeTruthy();
    });
  });
});
