import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunDetailsPanel } from "../RunDetailsPanel";

const EMPTY_PROPS = {
  runLoading: false,
  run: null,
  stepsLoading: false,
  steps: null,
  evidenceLoading: false,
  evidence: null,
  reportsLoading: false,
  reports: null,
  exportsLoading: false,
  exports: null,
};

describe("RunDetailsPanel", () => {
  it("prompts to select a run when no run is provided", () => {
    render(<RunDetailsPanel {...EMPTY_PROPS} />);
    expect(screen.getByText("Select a run to inspect.")).toBeInTheDocument();
  });

  it("shows a loading state while the run is loading", () => {
    render(<RunDetailsPanel {...EMPTY_PROPS} runLoading={true} />);
    expect(screen.getByText("Loading run...")).toBeInTheDocument();
  });

  it("renders run status, timestamps, and step counts", () => {
    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-1",
          plan_version_id: "v-1",
          status: "running",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          step_count: 4,
          executed_step_ids: ["s1", "s2"],
          is_stale: false,
          cancel_requested: false,
        }}
      />,
    );

    const statusRow = screen.getByText("Status:").parentElement;
    expect(statusRow).not.toBeNull();
    expect(within(statusRow as HTMLElement).getByText("running")).toBeInTheDocument();
    expect(screen.getByText("Steps:")).toBeInTheDocument();
    expect(screen.getByText("Executed:")).toBeInTheDocument();
    expect(screen.getByText("Finished:")).toBeInTheDocument();
  });

  it("shows a dash for an unfinished run", () => {
    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-1",
          plan_version_id: "v-1",
          status: "running",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          finished_at: null,
          step_count: 1,
          executed_step_ids: [],
          is_stale: false,
          cancel_requested: false,
        }}
      />,
    );
    const finishedRow = screen.getByText("Finished:").parentElement;
    expect(finishedRow).not.toBeNull();
    expect(within(finishedRow as HTMLElement).getByText("-")).toBeInTheDocument();
  });

  it("renders the latest error with an alert role", () => {
    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-1",
          plan_version_id: "v-1",
          status: "failed",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          step_count: 1,
          is_stale: false,
          cancel_requested: false,
          latest_error: { code: "RUN_EXECUTION_FAILED", message: "boom", severity: "error" },
        }}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("EXECUTION_FAILED");
    expect(alert).toHaveTextContent("boom");
  });

  it("renders the list of run steps", () => {
    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        steps={[
          {
            run_step_id: "rs-1",
            run_id: "r-1",
            step_id: "s1",
            plan_version_id: "v-1",
            status: "succeeded",
            started_at: "2024-01-01T00:00:00",
          },
        ]}
      />,
    );

    expect(screen.getByText("Run Steps")).toBeInTheDocument();
    expect(screen.getByText("s1")).toBeInTheDocument();
    const stepBlock = screen.getByText("s1").closest("div");
    expect(stepBlock).not.toBeNull();
    expect(within(stepBlock as HTMLElement).getByText("succeeded")).toBeInTheDocument();
  });

  it("shows an empty message when there are no run steps", () => {
    render(<RunDetailsPanel {...EMPTY_PROPS} steps={[]} />);
    expect(screen.getByText("No run steps.")).toBeInTheDocument();
  });

  it("renders evidence edges", () => {
    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        evidence={[
          {
            evidence_edge_id: "ee-1",
            run_id: "r-1",
            run_step_id: "rs-1",
            plan_version_id: "v-1",
            step_id: "s1",
            parent_step_id: "s0",
            source_run_id: "r-0",
            source_run_step_id: "rs-0",
            policy: "reuse",
            source_label: "source A",
            is_reused: true,
            is_stale: false,
            created_at: "2024-01-01T00:00:00",
          },
        ]}
      />,
    );

    expect(screen.getByText("Evidence Edges")).toBeInTheDocument();
    expect(screen.getByText("reuse")).toBeInTheDocument();
    expect(screen.getByText("source A")).toBeInTheDocument();
  });

  it("renders reports and exports with sizes", () => {
    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        reports={[
          {
            report_id: "rep-1",
            report_type: "manifest",
            path: "/tmp/report.json",
            created_at: "2024-01-01T00:00:00",
          },
        ]}
        exports={[
          {
            export_id: "exp-1",
            run_id: "r-1",
            export_type: "python_scorer",
            path: "/tmp/scorer.py",
            created_at: "2024-01-01T00:00:00",
            size_bytes: 2048,
          },
        ]}
      />,
    );

    expect(screen.getByText("Reports")).toBeInTheDocument();
    expect(screen.getByText("manifest")).toBeInTheDocument();
    expect(screen.getByText("/tmp/report.json")).toBeInTheDocument();
    expect(screen.getByText("Exports")).toBeInTheDocument();
    expect(screen.getByText("python_scorer")).toBeInTheDocument();
    expect(screen.getByText("2 KB")).toBeInTheDocument();
  });

  it("shows None. for empty file lists", () => {
    render(<RunDetailsPanel {...EMPTY_PROPS} reports={[]} exports={[]} />);
    expect(screen.getAllByText("None.").length).toBe(2);
  });
});
