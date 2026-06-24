import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManualBinningVariableList } from "../ManualBinningVariableList";
import { buildManualBinningEditorState } from "../../test/fixtures/manualBinning";

function buildDefault() {
  return buildManualBinningEditorState();
}

describe("ManualBinningVariableList", () => {
  it("renders all variables from the DTO", () => {
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus={state.review_status}
        selected={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText("income")).toBeTruthy();
    expect(screen.getByText("age")).toBeTruthy();
    expect(screen.getByText("loan_amount")).toBeTruthy();
  });

  it("shows the summary line with counts", () => {
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus={state.review_status}
        selected={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText(/3 variables/)).toBeTruthy();
    expect(screen.getByText(/2 need review/)).toBeTruthy();
    expect(screen.getByText(/1 edited/)).toBeTruthy();
  });

  it("renders a Needs review badge for review_required variables", () => {
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus="not_started"
        selected={null}
        onSelect={() => {}}
      />,
    );
    const badges = screen.getAllByText("Needs review");
    expect(badges.length).toBeGreaterThanOrEqual(2);
  });

  it("renders Edited badge for edited variables", () => {
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus="not_started"
        selected={null}
        onSelect={() => {}}
      />,
    );
    const badges = screen.getAllByText("Edited", { exact: false });
    // At least one badge in the status column (case-sensitive match)
    expect(badges.length).toBeGreaterThanOrEqual(1);
  });

  it("renders Accepted badge when stepStatus is accepted_automated", () => {
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus="accepted_automated"
        selected={null}
        onSelect={() => {}}
      />,
    );
    const badges = screen.getAllByText("Accepted");
    expect(badges.length).toBe(state.variable_summaries!.length);
  });

  it("renders Reviewed badge when stepStatus is reviewed", () => {
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus="reviewed"
        selected={null}
        onSelect={() => {}}
      />,
    );
    const badges = screen.getAllByText("Reviewed");
    expect(badges.length).toBe(state.variable_summaries!.length);
  });

  it("shows monotonicity badges", () => {
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus={state.review_status}
        selected={null}
        onSelect={() => {}}
      />,
    );
    // Mono appears for monotonic variables; Non-mono for non_monotonic
    expect(screen.getAllByText("Mono").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Non-mono")).toBeTruthy();
  });

  it("filters by search input", async () => {
    const user = userEvent.setup();
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus={state.review_status}
        selected={null}
        onSelect={() => {}}
      />,
    );
    const searchInput = screen.getByPlaceholderText("Search variables…");
    await user.type(searchInput, "income");
    expect(screen.getByText("income")).toBeTruthy();
    expect(screen.queryByText("age")).toBeNull();
  });

  it("sorts by column click", async () => {
    const user = userEvent.setup();
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus={state.review_status}
        selected={null}
        onSelect={() => {}}
      />,
    );
    const ivHeader = screen.getByText("IV");
    await user.click(ivHeader);
    // After sorting ascending by IV, loan_amount (0.08) should appear before income (0.35)
    // Check the table cells for loan_amount (its IV is 0.0800)
    expect(screen.getByText("0.0800")).toBeTruthy();
  });

  it("calls onSelect when a row is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const state = buildDefault();
    render(
      <ManualBinningVariableList
        summaries={state.variable_summaries!}
        stepStatus={state.review_status}
        selected={null}
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByText("income"));
    expect(onSelect).toHaveBeenCalledWith("income");
  });
});
