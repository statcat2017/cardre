import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ManualBinningBinTable } from "../ManualBinningBinTable";
import { buildManualBinningEditorState } from "../../test/fixtures/manualBinning";

describe("ManualBinningBinTable", () => {
  it("shows empty state when no variable selected", () => {
    render(<ManualBinningBinTable variable={null} sourceBins={null} summary={null} />);
    expect(screen.getByText("Select a variable to view bin details.")).toBeTruthy();
  });

  it("renders bin labels and ranges for a variable", () => {
    const state = buildManualBinningEditorState();
    const sourceBins = (state.source_bins_by_variable as Record<string, unknown>)["income"] as Record<string, unknown> | null;
    const summary = state.variable_summaries!.find((v) => v.variable === "income");
    render(<ManualBinningBinTable variable="income" sourceBins={sourceBins} summary={summary} />);
    expect(screen.getByText("0 - 30000")).toBeTruthy();
    expect(screen.getByText("30000 - 60000")).toBeTruthy();
    expect(screen.getByText("100000+")).toBeTruthy();
  });

  it("shows bin metadata: count, good, bad, bad rate, WOE", () => {
    const state = buildManualBinningEditorState();
    const sourceBins = (state.source_bins_by_variable as Record<string, unknown>)["income"] as Record<string, unknown> | null;
    const summary = state.variable_summaries!.find((v) => v.variable === "income");
    render(<ManualBinningBinTable variable="income" sourceBins={sourceBins} summary={summary} />);
    // First bin: count=200, good=150, bad=50, bad_rate=0.25, woe=0.2
    expect(screen.getByText("200")).toBeTruthy();
    expect(screen.getByText("150")).toBeTruthy();
    expect(screen.getAllByText("50").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("0.250").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("0.2000").length).toBeGreaterThanOrEqual(1);
  });

  it("shows missing/special flags", () => {
    const state = buildManualBinningEditorState();
    const sourceBins = (state.source_bins_by_variable as Record<string, unknown>)["income"] as Record<string, unknown> | null;
    const summary = state.variable_summaries!.find((v) => v.variable === "income");
    render(<ManualBinningBinTable variable="income" sourceBins={sourceBins} summary={summary} />);
    // The "Missing" row has both the label "Missing" and the flag "Missing"
    expect(screen.getAllByText("Missing").length).toBeGreaterThanOrEqual(1);
  });

  it("shows special value flag", () => {
    const state = buildManualBinningEditorState();
    const sourceBins = (state.source_bins_by_variable as Record<string, unknown>)["age"] as Record<string, unknown> | null;
    const summary = state.variable_summaries!.find((v) => v.variable === "age");
    render(<ManualBinningBinTable variable="age" sourceBins={sourceBins} summary={summary} />);
    expect(screen.getByText("Special")).toBeTruthy();
  });
});
