import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PlanSidebar } from "../PlanSidebar";

const plans = [
  { plan_id: "pl-1", name: "First Plan" },
  { plan_id: "pl-2", name: "Second Plan" },
];

const runs = [
  { run_id: "r-1", status: "running" },
  { run_id: "r-2", status: "completed" },
];

function renderSidebar(overrides: Partial<Parameters<typeof PlanSidebar>[0]> = {}) {
  const props = {
    plans,
    plansLoading: false,
    effectiveSelectedPlanId: null,
    onSelectPlan: vi.fn(),
    newPlanName: "",
    onNewPlanNameChange: vi.fn(),
    onCreatePlan: vi.fn(),
    createPlanPending: false,
    runs,
    versionSelected: true,
    effectiveSelectedRunId: null,
    onSelectRun: vi.fn(),
    ...overrides,
  };
  render(<PlanSidebar {...props} />);
  return props;
}

describe("PlanSidebar", () => {
  it("renders section headings", () => {
    renderSidebar();

    expect(screen.getByRole("heading", { name: "Plans" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Runs" })).toBeInTheDocument();
  });

  it("shows a loading message while plans are loading", () => {
    renderSidebar({ plansLoading: true, plans: undefined });

    expect(screen.getByText("Loading plans...")).toBeInTheDocument();
  });

  it("shows the empty message when there are no plans", () => {
    renderSidebar({ plans: [] });

    expect(screen.getByText("No plans yet.")).toBeInTheDocument();
  });

  it("renders the plans with their ids", () => {
    renderSidebar();

    expect(screen.getByText("First Plan")).toBeInTheDocument();
    expect(screen.getByText("pl-1")).toBeInTheDocument();
    expect(screen.getByText("Second Plan")).toBeInTheDocument();
    expect(screen.getByText("pl-2")).toBeInTheDocument();
  });

  it("calls onSelectPlan when a plan is clicked", async () => {
    const user = userEvent.setup();
    const { onSelectPlan } = renderSidebar();

    await user.click(screen.getByRole("button", { name: /First Plan/ }));

    expect(onSelectPlan).toHaveBeenCalledTimes(1);
    expect(onSelectPlan).toHaveBeenCalledWith("pl-1");
  });

  it("renders runs with status and id", () => {
    renderSidebar();

    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("r-1")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("r-2")).toBeInTheDocument();
  });

  it("calls onSelectRun when a run is clicked", async () => {
    const user = userEvent.setup();
    const { onSelectRun } = renderSidebar();

    await user.click(screen.getByRole("button", { name: /r-2/ }));

    expect(onSelectRun).toHaveBeenCalledTimes(1);
    expect(onSelectRun).toHaveBeenCalledWith("r-2");
  });

  it("shows no-runs message based on version selection", () => {
    renderSidebar({ runs: [], versionSelected: true });
    expect(screen.getByText("No runs for this version.")).toBeInTheDocument();
  });

  it("shows generic no-runs message when no version is selected", () => {
    renderSidebar({ runs: [], versionSelected: false });
    expect(screen.getByText("No runs yet.")).toBeInTheDocument();
  });

  it("updates the new plan name input", async () => {
    const user = userEvent.setup();
    const { onNewPlanNameChange } = renderSidebar();

    await user.type(screen.getByPlaceholderText("New plan name"), "My Plan");

    expect(onNewPlanNameChange).toHaveBeenCalled();
  });

  it("shows the pending state and disables the submit button while creating", () => {
    const { onCreatePlan } = renderSidebar({ newPlanName: "My Plan", createPlanPending: true });

    const button = screen.getByRole("button", { name: "Creating..." });
    expect(button).toBeDisabled();
    expect(onCreatePlan).not.toHaveBeenCalled();
  });

  it("submits the create-plan form when the button is enabled", async () => {
    const user = userEvent.setup();
    const { onCreatePlan } = renderSidebar({ newPlanName: "My Plan" });

    await user.click(screen.getByRole("button", { name: "Create plan" }));

    expect(onCreatePlan).toHaveBeenCalledTimes(1);
  });
});
