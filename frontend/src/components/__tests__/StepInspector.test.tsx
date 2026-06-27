import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StepInspector } from "../StepInspector";
import type { StepStatus } from "../../types";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const baseStep = (step_id: string, overrides?: Partial<StepStatus>): StepStatus =>
  ({
    step_id,
    node_type: "cardre.logistic_regression",
    status: "pending",
    display_name: "Logistic Regression",
    ...overrides,
  }) as StepStatus;

describe("StepInspector", () => {
  it("shows placeholder when no step is selected", () => {
    renderWithClient(
      <StepInspector
        step={null}
        planId="p1"
        projectId="proj1"
        basePlanVersionId="v1"
        currentParams={{}}
        onPlanRefreshed={() => {}}
        onEditManualBinning={() => {}}
      />,
    );
    expect(screen.getByText("Select a step to inspect")).toBeTruthy();
  });

  it("renders the Next-action tab by default for a step", () => {
    renderWithClient(
      <StepInspector
        step={baseStep("cardre.logistic_regression")}
        planId="p1"
        projectId="proj1"
        basePlanVersionId="v1"
        currentParams={{}}
        onPlanRefreshed={() => {}}
        onEditManualBinning={() => {}}
      />,
    );
    expect(screen.getByText("Next action")).toBeTruthy();
  });

  it("resets to the Next-action tab when the step changes", () => {
    const { rerender } = renderWithClient(
      <StepInspector
        step={baseStep("cardre.logistic_regression")}
        planId="p1"
        projectId="proj1"
        basePlanVersionId="v1"
        currentParams={{}}
        onPlanRefreshed={() => {}}
        onEditManualBinning={() => {}}
      />,
    );
    rerender(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <StepInspector
          step={baseStep("cardre.binning")}
          planId="p1"
          projectId="proj1"
          basePlanVersionId="v1"
          currentParams={{}}
          onPlanRefreshed={() => {}}
          onEditManualBinning={() => {}}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Next action")).toBeTruthy();
  });
});
