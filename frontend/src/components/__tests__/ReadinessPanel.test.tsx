import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReadinessPanel } from "../ReadinessPanel";

function makeReady(overrides: Record<string, unknown> = {}) {
  return {
    ready: true,
    status: "ready",
    blockers: [],
    warnings: [],
    ...overrides,
  };
}

describe("ReadinessPanel", () => {
  it('shows "Select a branch." when targetBranchId is null', () => {
    render(
      <ReadinessPanel
        targetBranchId={null}
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={undefined}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("Select a branch.")).toBeInTheDocument();
  });

  it('shows "No successful run yet." when latestRunId is null', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId={null}
        branchName={null}
        reportMode="branch"
        readinessData={undefined}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("No successful run yet.")).toBeInTheDocument();
  });

  it('shows "Checking readiness…" while loading', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={undefined}
        readinessLoading={true}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("Checking readiness…")).toBeInTheDocument();
    expect(screen.getByText("Checking…")).toBeInTheDocument();
  });

  it('shows "Checking readiness…" while isFetching (refetch)', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={makeReady()}
        readinessLoading={false}
        readinessIsFetching={true}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    // Stale data is not shown — loading state takes priority
    expect(screen.getByText("Checking readiness…")).toBeInTheDocument();
  });

  it('shows "Readiness check failed." on error', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={undefined}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={new Error("Connection refused")}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText(/Readiness check failed/)).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
  });

  it('shows "Blocked" with blocker row and Go to step button', async () => {
    const onStepSelect = vi.fn();
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={makeReady({
          ready: false,
          blockers: [{ code: "MISSING_STEP", message: "Step abc missing.", step_id: "abc" }],
        })}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={null}
        onStepSelect={onStepSelect}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("MISSING_STEP:")).toBeInTheDocument();

    const goToStep = screen.getByRole("button", { name: /go to step/i });
    await userEvent.click(goToStep);
    expect(onStepSelect).toHaveBeenCalledWith("abc");
  });

  it('shows "Ready with warnings." when ready with warnings', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={makeReady({
          warnings: [{ code: "NO_OOT", message: "No OOT sample.", step_id: null }],
        })}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("Ready.")).toBeInTheDocument();
    expect(screen.getByText("NO_OOT:")).toBeInTheDocument();
  });

  it('shows "Ready." when ready with no blockers or warnings', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={makeReady()}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("Ready.")).toBeInTheDocument();
  });

  it("shows freshness copy with branch name, run id, and mode when data present", () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run_abc123"
        branchName="Baseline"
        reportMode="branch"
        readinessData={makeReady()}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText(/Baseline/)).toBeInTheDocument();
    expect(screen.getByText(/run_abc/)).toBeInTheDocument();
    expect(screen.getByText(/branch/)).toBeInTheDocument();
    expect(screen.getByText(/TopBar readiness badge/)).toBeInTheDocument();
  });

  it('recheck button shows "Checking…" when loading', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={makeReady()}
        readinessLoading={true}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("Checking…")).toBeInTheDocument();
  });

  it('recheck button shows "Re-check readiness" when not loading', () => {
    render(
      <ReadinessPanel
        targetBranchId="br1"
        latestRunId="run1"
        branchName={null}
        reportMode="branch"
        readinessData={makeReady()}
        readinessLoading={false}
        readinessIsFetching={false}
        readinessError={null}
        onRecheck={vi.fn()}
      />,
    );
    expect(screen.getByText("Re-check readiness")).toBeInTheDocument();
  });
});
