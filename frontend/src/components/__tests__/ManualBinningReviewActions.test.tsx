import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ManualBinningReviewActions } from "../ManualBinningReviewActions";
import {
  buildManualBinningEditorState,
  buildReviewedEditorState,
  buildAcceptedEditorState,
  buildBlockedEditorState,
} from "../../test/fixtures/manualBinning";

function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("ManualBinningReviewActions", () => {
  it("shows step summary counts", () => {
    const state = buildManualBinningEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    expect(screen.getByText(/1 of 3 variables reviewed/)).toBeTruthy();
    expect(screen.getByText(/1 edited/)).toBeTruthy();
  });

  it("disables mark review complete when blocking issues exist", () => {
    const state = buildBlockedEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    const btn = screen.getByText("Mark review complete");
    expect(btn).toBeDisabled();
  });

  it("enables mark review complete when no blocking issues", () => {
    const state = buildManualBinningEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    const btn = screen.getByText("Mark review complete");
    expect(btn).not.toBeDisabled();
  });

  it("shows blocking issues when present", () => {
    const state = buildBlockedEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    expect(screen.getByText("BLOCKING ISSUES")).toBeTruthy();
    expect(screen.getByText(/UNREVIEWED_REQUIRED_VARIABLE/)).toBeTruthy();
  });

  it("shows reviewed state banner when review_status is reviewed", () => {
    const state = buildReviewedEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    expect(screen.getByText("Review complete")).toBeTruthy();
    expect(screen.getByText(/alice/)).toBeTruthy();
  });

  it("shows accepted banner when review_status is accepted_automated", () => {
    const state = buildAcceptedEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    expect(screen.getByText("Automated bins accepted")).toBeTruthy();
  });

  it("shows reason form when clicking Mark review complete", async () => {
    const user = userEvent.setup();
    const state = buildManualBinningEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    await user.click(screen.getByText("Mark review complete"));
    expect(screen.getByText(/Provide a reason/)).toBeTruthy();
    expect(screen.getByText(/Select a reason code/)).toBeTruthy();
    expect(
      screen.getByPlaceholderText("Describe why you are marking review complete…"),
    ).toBeTruthy();
  });

  it("disables confirm button until reason code and text are supplied", async () => {
    const user = userEvent.setup();
    const state = buildManualBinningEditorState();
    renderWithQuery(
      <ManualBinningReviewActions
        state={state}
        planId="plan1"
        stepId="manual-binning"
        basePlanVersionId="pv1"
        onPlanRefreshed={() => {}}
      />,
    );
    await user.click(screen.getByText("Mark review complete"));
    const confirmBtn = screen.getByText("Confirm review");
    expect(confirmBtn).toBeDisabled();

    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "monotonicity");
    const textarea = screen.getByPlaceholderText("Describe why you are marking review complete…");
    await user.type(textarea, "All bins look good.");
    expect(confirmBtn).not.toBeDisabled();
  });
});
