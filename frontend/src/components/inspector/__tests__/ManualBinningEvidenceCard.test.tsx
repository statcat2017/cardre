import { describe, it, expect, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../../test/server";
import { ManualBinningEvidenceCard } from "../ManualBinningEvidenceCard";
import {
  buildManualBinningEditorState,
  buildReviewedEditorState,
  buildAcceptedEditorState,
  buildBlockedEditorState,
} from "../../../test/fixtures/manualBinning";

const BASE = "http://127.0.0.1:8752";

function renderCard(mbState: Record<string, unknown> | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const handler = mbState
    ? http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () => HttpResponse.json(mbState))
    : undefined;
  if (handler) server.use(handler);
  return render(
    <QueryClientProvider client={qc}>
      <ManualBinningEvidenceCard projectId="prj1" planId="plan1" stepId="manual-binning" />
    </QueryClientProvider>,
  );
}

describe("ManualBinningEvidenceCard", () => {
  afterEach(() => server.resetHandlers());

  it("shows error state when API fails", async () => {
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () =>
        HttpResponse.json(null, { status: 500 }),
      ),
    );
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ManualBinningEvidenceCard projectId="prj1" planId="plan1" stepId="manual-binning" />
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText(/Could not load manual-binning review state/)).toBeInTheDocument();
    });
  });

  it("shows not-ready state when editor is not ready", async () => {
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () =>
        HttpResponse.json(buildManualBinningEditorState({ ready: false, blocked_reason: "Upstream stale." })),
      ),
    );
    renderCard();
    await waitFor(() => {
      expect(screen.getByText(/run the pathway first/)).toBeInTheDocument();
    });
  });

  it("shows Not reviewed state", async () => {
    const state = buildManualBinningEditorState();
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () => HttpResponse.json(state)),
    );
    renderCard();
    await waitFor(() => {
      expect(screen.getByText("Not reviewed")).toBeInTheDocument();
      expect(screen.getByText(/1 of 3 variables reviewed/)).toBeInTheDocument();
      expect(screen.getByText(/1 edited/)).toBeInTheDocument();
    });
  });

  it("shows reviewed state with reviewer metadata", async () => {
    const state = buildReviewedEditorState();
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () => HttpResponse.json(state)),
    );
    renderCard();
    await waitFor(() => {
      expect(screen.getByText("Review complete")).toBeInTheDocument();
      expect(screen.getByText(/alice/)).toBeInTheDocument();
      expect(screen.getByText(/All bins look clean/)).toBeInTheDocument();
    });
  });

  it("shows accepted automated state", async () => {
    const state = buildAcceptedEditorState();
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () => HttpResponse.json(state)),
    );
    renderCard();
    await waitFor(() => {
      expect(screen.getByText("Automated bins accepted")).toBeInTheDocument();
    });
  });

  it("labels blockers as blockers (distinct from warnings)", async () => {
    const state = buildBlockedEditorState();
    server.use(
      http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, () => HttpResponse.json(state)),
    );
    renderCard();
    await waitFor(() => {
      expect(screen.getByText(/1 blocker/)).toBeInTheDocument();
      expect(screen.getByText(/1 warning/)).toBeInTheDocument();
    });
  });
});
