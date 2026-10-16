import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

  it("downloads an available scoring export and shows success", async () => {
    const user = userEvent.setup();
    const exportItem = {
      export_id: "artifact-1",
      artifact_id: "artifact-1",
      run_id: "r-1",
      export_type: "scorecard_csv",
      path: "scorecard.csv",
      file_name: "scorecard.csv",
      media_type: "text/csv",
      created_at: "2024-01-01T00:00:00",
      size_bytes: 0,
    };
    const onDownloadExport = vi.fn().mockResolvedValue(undefined);

    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-1",
          plan_version_id: "v-1",
          status: "succeeded",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          step_count: 31,
          is_stale: false,
          cancel_requested: false,
        }}
        exports={[exportItem]}
        onDownloadExport={onDownloadExport}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Download scorecard.csv" }));

    expect(onDownloadExport).toHaveBeenCalledWith(exportItem);
    expect(await screen.findByText("Downloaded scorecard.csv.")).toBeInTheDocument();
  });

  it("starts report generation for a succeeded run and shows readiness blockers", async () => {
    const user = userEvent.setup();
    const onGenerateReport = vi.fn().mockResolvedValue(undefined);
    const succeededRun = {
      run_id: "r-1",
      plan_version_id: "v-1",
      status: "succeeded",
      run_scope: "full_plan",
      force: false,
      started_at: "2024-01-01T00:00:00",
      step_count: 31,
      is_stale: false,
      cancel_requested: false,
    };

    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={succeededRun}
        reports={[]}
        onGenerateReport={onGenerateReport}
        reportGenerationError={{
          message: "Report generation is blocked by readiness checks.",
          context: {
            blockers: [{ code: "MISSING_EVIDENCE", message: "Validation evidence is missing." }],
          },
        }}
      />,
    );

    expect(
      screen.getByText("Report generation is blocked by readiness checks."),
    ).toBeInTheDocument();
    expect(screen.getByText("Validation evidence is missing.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    expect(onGenerateReport).toHaveBeenCalledOnce();
  });

  it("generates an audit pack and keeps partial status and warnings visible", async () => {
    const user = userEvent.setup();
    const onGenerateAuditPack = vi.fn().mockResolvedValue(undefined);
    const onDownloadAuditPack = vi.fn().mockResolvedValue(undefined);
    const run = {
      run_id: "r-1",
      plan_version_id: "v-1",
      status: "succeeded",
      run_scope: "full_plan",
      force: false,
      started_at: "2024-01-01T00:00:00",
      step_count: 31,
      is_stale: false,
      cancel_requested: false,
    };
    const partialPack = {
      export_id: "exp-1",
      run_id: "r-1",
      export_type: "audit_pack",
      path: "exports/audit-r-1.zip",
      file_name: "audit-r-1.zip",
      media_type: "application/zip",
      download_url: "/projects/p-1/runs/r-1/exports/exp-1/download",
      partial: true,
      warnings: ["Canonical manifest is unavailable."],
      created_at: "2024-01-01T00:00:00",
      size_bytes: 123,
    };

    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={run}
        exports={[partialPack]}
        onGenerateAuditPack={onGenerateAuditPack}
        onDownloadAuditPack={onDownloadAuditPack}
      />,
    );

    expect(
      screen.getByText("Audit packs exclude source and scored row-level data by default."),
    ).toBeInTheDocument();
    expect(screen.getByText("Partial audit pack")).toBeInTheDocument();
    expect(screen.getByText("Canonical manifest is unavailable.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate audit pack" }));
    expect(onGenerateAuditPack).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Download audit-r-1.zip" }));
    expect(onDownloadAuditPack).toHaveBeenCalledWith(partialPack);
    expect(await screen.findByText("Downloaded audit-r-1.zip.")).toBeInTheDocument();
  });

  it("shows audit pack generation errors and pending state", () => {
    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-1",
          plan_version_id: "v-1",
          status: "succeeded",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          step_count: 31,
          is_stale: false,
          cancel_requested: false,
        }}
        onGenerateAuditPack={vi.fn().mockResolvedValue(undefined)}
        auditPackGenerationPending={true}
        auditPackGenerationError={new Error("Audit pack could not be generated.")}
      />,
    );

    expect(screen.getByRole("button", { name: "Preparing audit pack…" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Audit pack could not be generated.");
  });

  it("opens and downloads a listed model report", async () => {
    const user = userEvent.setup();
    const report = {
      report_id: "rep-1",
      run_id: "r-1",
      report_type: "report",
      path: "reports/r-1/report.html",
      created_at: "2024-01-01T00:00:00",
      file_name: "model-development-report.html",
      open_url: "/projects/p-1/runs/r-1/reports/rep-1/html",
      download_url: "/projects/p-1/runs/r-1/reports/rep-1/download",
    };
    const onOpenReport = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => "<h1>report</h1>",
      blob: async () => new Blob(["<h1>report</h1>"]),
    } as Response);
    const onDownloadReport = vi
      .fn()
      .mockResolvedValue({ blob: async () => new Blob(["<h1>report</h1>"]) });
    const createObjectURL = vi.fn().mockReturnValue("blob:report");
    vi.spyOn(window, "open").mockReturnValue(null);
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL: vi.fn() });

    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-1",
          plan_version_id: "v-1",
          status: "succeeded",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          step_count: 31,
          is_stale: false,
          cancel_requested: false,
        }}
        reports={[report]}
        onOpenReport={onOpenReport}
        onDownloadReport={onDownloadReport}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(onOpenReport).toHaveBeenCalledWith(report);
    const preview = await screen.findByTitle("Model development report content");
    expect(preview).toHaveAttribute("srcdoc", "<h1>report</h1>");
    expect(preview).toHaveAttribute("sandbox", "");
    await user.click(screen.getByRole("button", { name: "Close report preview" }));
    expect(screen.queryByTitle("Model development report content")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(onDownloadReport).toHaveBeenCalledWith(report);

    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("distinguishes a download failure and missing outputs", async () => {
    const user = userEvent.setup();
    const onDownloadExport = vi.fn().mockRejectedValue(new Error("artifact is unavailable"));

    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-1",
          plan_version_id: "v-1",
          status: "succeeded",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          step_count: 31,
          is_stale: false,
          cancel_requested: false,
        }}
        exports={[
          {
            export_id: "artifact-1",
            artifact_id: "artifact-1",
            run_id: "r-1",
            export_type: "python_scorer",
            path: "scorecard.py",
            file_name: "scorecard.py",
            media_type: "text/x-python",
            created_at: "2024-01-01T00:00:00",
            size_bytes: 0,
          },
        ]}
        onDownloadExport={onDownloadExport}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Download scorecard.py" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Download failed: artifact is unavailable",
    );

    render(
      <RunDetailsPanel
        {...EMPTY_PROPS}
        run={{
          run_id: "r-2",
          plan_version_id: "v-1",
          status: "succeeded",
          run_scope: "full_plan",
          force: false,
          started_at: "2024-01-01T00:00:00",
          step_count: 31,
          is_stale: false,
          cancel_requested: false,
        }}
        exports={[]}
      />,
    );
    expect(screen.getByText("No exports are available for this run yet.")).toBeInTheDocument();
  });

  it("shows None. for empty file lists", () => {
    render(<RunDetailsPanel {...EMPTY_PROPS} reports={[]} exports={[]} />);
    expect(
      screen.getByText("A report can be generated after this run succeeds."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Exports are unavailable until this run succeeds."),
    ).toBeInTheDocument();
  });
});
