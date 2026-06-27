import React from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { EvidenceTab } from "../EvidenceTab";
import { server } from "../../../test/server";

const BASE = "http://127.0.0.1:8752";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function makeEvidenceResponse(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "run1",
    step_id: "step1",
    items: [],
    status: "available",
    checked_at: "2026-06-23T00:00:00Z",
    target_branch_id: "",
    canonical_step_id: null,
    ...overrides,
  };
}

describe("EvidenceTab", () => {
  beforeEach(() => {
    server.resetHandlers();
  });

  it('renders "no-run" state when runId is null', () => {
    renderWithClient(
      <EvidenceTab
        runId={null}
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    expect(screen.getByText(/No run yet/)).toBeInTheDocument();
  });

  it('renders "no-evidence" state when tab is not "evidence" (hook disabled)', async () => {
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="guidance"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/No evidence found/)).toBeInTheDocument();
    });
  });

  it('renders "loading" state', () => {
    // Delayed response so isLoading stays true
    server.use(
      http.get(`${BASE}/runs/:runId/steps/:stepId/evidence`, () =>
        HttpResponse.json(makeEvidenceResponse(), { status: 200 }),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    expect(screen.getByText(/Loading evidence/)).toBeInTheDocument();
  });

  it('renders "load-failed" state on API error', async () => {
    server.use(
      http.get(`${BASE}/runs/:runId/steps/:stepId/evidence`, () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Evidence could not be loaded/)).toBeInTheDocument();
    });
  });

  it('renders "no-evidence" state when items empty', async () => {
    server.use(
      http.get(`${BASE}/runs/:runId/steps/:stepId/evidence`, () =>
        HttpResponse.json(makeEvidenceResponse({ status: "missing" })),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/No evidence found/)).toBeInTheDocument();
    });
  });

  it('renders "stale" state', async () => {
    server.use(
      http.get(`${BASE}/runs/:runId/steps/:stepId/evidence`, () =>
        HttpResponse.json(makeEvidenceResponse({
          status: "stale",
          items: [{
            artifact_id: "art-1",
            artifact_type: "woe-iv-evidence",
            role: "train",
            media_type: "application/json",
            evidence_kind: "woe-iv",
            logical_hash: "abc123",
            created_at: "2026-06-23T00:00:00Z",
            is_stale: true,
            staleness_reason: "upstream_stale",
            canonical_step_id: "final-woe-iv",
            source_step_id: "step1",
            source_branch_id: null,
            status: "stale",
            summary: { selected_variable_count: 12, iv_min: 0.18, iv_max: 0.42 },
            warnings: [],
          }],
        })),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Evidence is stale/)).toBeInTheDocument();
    });
  });

  it('renders "partial" state', async () => {
    server.use(
      http.get(`${BASE}/runs/:runId/steps/:stepId/evidence`, () =>
        HttpResponse.json(makeEvidenceResponse({
          status: "partial",
          items: [{
            artifact_id: "art-1",
            artifact_type: "woe-iv-evidence",
            role: "train",
            media_type: "application/json",
            evidence_kind: "woe-iv",
            logical_hash: "abc123",
            created_at: "2026-06-23T00:00:00Z",
            is_stale: false,
            staleness_reason: null,
            canonical_step_id: "final-woe-iv",
            source_step_id: "step1",
            source_branch_id: null,
            status: "unsupported",
            summary: { unsupported_kind: true },
            warnings: [],
          }],
        })),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Partial evidence/)).toBeInTheDocument();
    });
  });

  it('renders "available" state with summary', async () => {
    server.use(
      http.get(`${BASE}/runs/:runId/steps/:stepId/evidence`, () =>
        HttpResponse.json(makeEvidenceResponse({
          status: "available",
          items: [{
            artifact_id: "art-woe-001",
            artifact_type: "woe-iv-evidence",
            role: "train",
            media_type: "application/json",
            evidence_kind: "woe-iv",
            logical_hash: "abc123def456",
            created_at: "2026-06-23T10:14:00Z",
            is_stale: false,
            staleness_reason: null,
            canonical_step_id: "final-woe-iv",
            source_step_id: "step1",
            source_branch_id: null,
            status: "available",
            summary: { selected_variable_count: 12, iv_min: 0.18, iv_max: 0.42, top_variables: [{ name: "income_band", iv: 0.42 }] },
            warnings: [],
          }],
        })),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/WOE\/IV Evidence/)).toBeInTheDocument();
    });
    expect(screen.getByText("Current")).toBeInTheDocument();
  });

  it("renders warnings on evidence card", async () => {
    server.use(
      http.get(`${BASE}/runs/:runId/steps/:stepId/evidence`, () =>
        HttpResponse.json(makeEvidenceResponse({
          status: "available",
          items: [{
            artifact_id: "art-warn",
            artifact_type: "validation-metrics",
            role: "test",
            media_type: "application/json",
            evidence_kind: "validation-metrics",
            logical_hash: "def",
            created_at: "2026-06-23T00:00:00Z",
            is_stale: false,
            staleness_reason: null,
            canonical_step_id: "validation-metrics",
            source_step_id: "step1",
            source_branch_id: null,
            status: "available",
            summary: { gini: 0.45, ks: 0.31 },
            warnings: ["PSI exceeds threshold for train segment."],
          }],
        })),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="step1"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/PSI exceeds threshold/)).toBeInTheDocument();
    });
  });

  it("renders manual-binning evidence card when stepId contains manual-binning", async () => {
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () =>
        HttpResponse.json({ ready: true, review_status: "not_started", reviewed: false, accept_automated: false, variable_summaries: [], blocking_issues: [], selected_variables: [], source_bins_by_variable: {}, current_overrides: [], warnings: [], plan_id: "plan1", plan_version_id: "pv1", step_id: "manual-binning", project_id: "prj1" }),
      ),
    );
    renderWithClient(
      <EvidenceTab
        runId="run1"
        stepId="manual-binning"
        projectId="prj1"
        tab="evidence"
        planId="plan1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Manual binning review/)).toBeInTheDocument();
    });
  });
});
