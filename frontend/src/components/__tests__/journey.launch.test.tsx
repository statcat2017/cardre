import { describe, it, expect, vi, afterAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProjectView } from "../ProjectView";
import {
  PROJECT_ID,
  PLAN_ID,
  BRANCH_ID,
  RUN_ID,
  buildProject,
  buildPlanWithLaunchSteps,
  buildBaselineBranch,
  buildSucceededRun,
  buildWorkflowGuidanceBuildPhase,
  buildWorkflowGuidanceExportPhase,
  buildReportReadinessBlocked,
  buildReportReadinessReady,
  buildGenerateReportResponse,
} from "../../test/fixtures/launchJourney";

let originalFetch: typeof globalThis.fetch;

function setupFetchStub(
  readinessResponse: () => { body: Record<string, unknown>; status?: number } | null,
  generateCheck?: (body: Record<string, unknown>) => void,
) {
  originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn((url: string | URL | Request, opts?: RequestInit) => {
    const urlStr = typeof url === "string" ? url : url.toString();
    if (urlStr.includes("/report-readiness")) {
      const res = readinessResponse();
      if (res === null) {
        return Promise.reject(new Error("Readiness check failed"));
      }
      return Promise.resolve(new Response(
        JSON.stringify(res.body),
        { status: res.status ?? 200, headers: { "Content-Type": "application/json" } },
      ));
    }
    if (urlStr.includes("/reports") && opts?.method === "POST") {
      const body = JSON.parse(opts?.body as string);
      generateCheck?.(body);
      return Promise.resolve(new Response(
        JSON.stringify(buildGenerateReportResponse()),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ));
    }
    if (urlStr.includes("/reports")) {
      return Promise.resolve(new Response(
        JSON.stringify([]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ));
    }
    return originalFetch(url, opts);
  }) as typeof fetch;
}

function restoreFetch() {
  if (originalFetch) globalThis.fetch = originalFetch;
}

function createClient(entries: Array<[Array<string | number | null>, unknown]>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 300_000 } },
  });
  for (const [key, data] of entries) {
    client.setQueryData(key, data);
  }
  return client;
}

describe("Guided launch journey", () => {
  afterAll(() => {
    restoreFetch();
  });

  it("loads guided project journey and shows pathway readiness", async () => {
    const project = buildProject();
    const plan = buildPlanWithLaunchSteps();
    const guidance = buildWorkflowGuidanceBuildPhase();
    const branch = buildBaselineBranch();

    const client = createClient([
      [["project", PROJECT_ID], project],
      [["projectPlans", PROJECT_ID], { plans: [{ plan_id: PLAN_ID, name: "Scorecard Pathway", is_default: true, project_id: PROJECT_ID }] }],
      [["plan", PLAN_ID], plan],
      [["projectBranches", PROJECT_ID], { branches: [branch] }],
      // Guidance hook fires with runId=null first
      [["workflowGuidance", PROJECT_ID, PLAN_ID, BRANCH_ID, null], guidance],
    ]);

    render(
      <QueryClientProvider client={client}>
        <ProjectView projectId={PROJECT_ID} onBack={() => {}} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Test Project")).toBeInTheDocument();
    });

    expect(screen.getByText("Configure target")).toBeInTheDocument();
    expect(screen.getByText("build")).toBeInTheDocument();
  });

  it("report blocker Go to step selects the blocked step and switches to pathway", async () => {
    const project = buildProject();
    const plan = buildPlanWithLaunchSteps();
    const branch = buildBaselineBranch();
    const run = buildSucceededRun();
    const guidance = buildWorkflowGuidanceExportPhase();
    const blockerStepId = "target-definition";
    const blockedReadiness = buildReportReadinessBlocked(blockerStepId);

    setupFetchStub(() => ({ body: blockedReadiness }));

    const client = createClient([
      [["project", PROJECT_ID], project],
      [["projectPlans", PROJECT_ID], { plans: [{ plan_id: PLAN_ID, name: "Scorecard Pathway", is_default: true, project_id: PROJECT_ID }] }],
      [["plan", PLAN_ID], plan],
      [["projectBranches", PROJECT_ID], { branches: [branch] }],
      // Guidance hook fires with runId=null first, then refetches with RUN_ID
      [["workflowGuidance", PROJECT_ID, PLAN_ID, BRANCH_ID, null], guidance],
      [["workflowGuidance", PROJECT_ID, PLAN_ID, BRANCH_ID, RUN_ID], guidance],
      [["projectRuns", PROJECT_ID], { runs: [run] }],
    ]);

    render(
      <QueryClientProvider client={client}>
        <ProjectView projectId={PROJECT_ID} onBack={() => {}} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Export audit pack")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("Export audit pack"));

    await waitFor(() => {
      expect(screen.getByText("Blocked")).toBeInTheDocument();
    });

    const goToStep = screen.getByRole("button", { name: /go to step/i });
    expect(goToStep).toBeInTheDocument();

    await userEvent.click(goToStep);

    await waitFor(() => {
      expect(screen.queryByText("Audit Pack Export")).not.toBeInTheDocument();
    });

    restoreFetch();
  });

  it("ready report enables generate and calls generate with the right branch and run", async () => {
    const project = buildProject();
    const plan = buildPlanWithLaunchSteps();
    const branch = buildBaselineBranch();
    const run = buildSucceededRun();
    const guidance = buildWorkflowGuidanceExportPhase();

    let capturedGenerateBody: Record<string, unknown> | null = null;

    setupFetchStub(
      () => ({ body: buildReportReadinessReady() }),
      (body) => { capturedGenerateBody = body; },
    );

    const client = createClient([
      [["project", PROJECT_ID], project],
      [["projectPlans", PROJECT_ID], { plans: [{ plan_id: PLAN_ID, name: "Scorecard Pathway", is_default: true, project_id: PROJECT_ID }] }],
      [["plan", PLAN_ID], plan],
      [["projectBranches", PROJECT_ID], { branches: [branch] }],
      [["workflowGuidance", PROJECT_ID, PLAN_ID, BRANCH_ID, null], guidance],
      [["workflowGuidance", PROJECT_ID, PLAN_ID, BRANCH_ID, RUN_ID], guidance],
      [["projectRuns", PROJECT_ID], { runs: [run] }],
    ]);

    render(
      <QueryClientProvider client={client}>
        <ProjectView projectId={PROJECT_ID} onBack={() => {}} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Export audit pack")).toBeInTheDocument();
    });
    await userEvent.click(screen.getByText("Export audit pack"));

    await waitFor(() => {
      const generateBtn = screen.getByRole("button", { name: /generate audit pack/i });
      expect(generateBtn).toBeEnabled();
    });

    await userEvent.click(screen.getByRole("button", { name: /generate audit pack/i }));

    await waitFor(() => {
      expect(capturedGenerateBody).not.toBeNull();
      expect(capturedGenerateBody!.target_branch_id).toBe(BRANCH_ID);
      expect(capturedGenerateBody!.report_mode).toBe("branch");
    });

    restoreFetch();
  });
});
