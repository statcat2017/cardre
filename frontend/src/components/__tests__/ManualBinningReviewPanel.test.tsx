import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ManualBinningReviewPanel } from "../ManualBinningReviewPanel";
import { buildManualBinningEditorState } from "../../test/fixtures/manualBinning";

describe("ManualBinningReviewPanel", () => {
  it("shows empty state when no variable selected", () => {
    const state = buildManualBinningEditorState();
    render(<ManualBinningReviewPanel variable={null} state={state} />);
    expect(screen.getByText("Select a variable to review.")).toBeTruthy();
  });

  it("shows variable overview when a variable is selected", () => {
    const state = buildManualBinningEditorState();
    render(<ManualBinningReviewPanel variable="income" state={state} />);
    expect(screen.getByText("income")).toBeTruthy();
    expect(screen.getByText("numeric")).toBeTruthy();
    // IV value should be present in the overview grid
    expect(screen.getByText("0.3500")).toBeTruthy();
  });

  it("shows evidence summary line", () => {
    const state = buildManualBinningEditorState();
    render(<ManualBinningReviewPanel variable="income" state={state} />);
    expect(screen.getByText(/bins/)).toBeTruthy();
    expect(screen.getByText(/bad rate/)).toBeTruthy();
    expect(screen.getByText(/WOE/)).toBeTruthy();
  });

  it("shows warnings for a variable with issues", () => {
    const state = buildManualBinningEditorState();
    // age is non_monotonic, has special bins, and is review_required
    render(<ManualBinningReviewPanel variable="age" state={state} />);
    expect(screen.getByText("NON_MONOTONIC")).toBeTruthy();
    expect(screen.getByText("SPECIAL_BINS")).toBeTruthy();
  });

  it("shows recommended action for non_monotonic", () => {
    const state = buildManualBinningEditorState();
    render(<ManualBinningReviewPanel variable="age" state={state} />);
    expect(screen.getByText(/Review monotonicity/)).toBeTruthy();
  });

  it("shows recommended action for sparse bin", () => {
    const state = buildManualBinningEditorState();
    render(<ManualBinningReviewPanel variable="loan_amount" state={state} />);
    expect(screen.getByText(/sparse/)).toBeTruthy();
  });

  it("shows recommended action for variable with missing bins", () => {
    const state = buildManualBinningEditorState();
    render(<ManualBinningReviewPanel variable="income" state={state} />);
    expect(screen.getByText(/missing_value_treatment/)).toBeTruthy();
  });
});
