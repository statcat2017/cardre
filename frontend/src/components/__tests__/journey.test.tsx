import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("Journey acceptance", () => {
  it("shows guidance-driven CTA label in TopBar when guidance loads", async () => {
    server.use(
      http.get("/plans/:planId/workflow-guidance", () =>
        HttpResponse.json({
          phase: "build",
          next_action: {
            kind: "configure_step",
            label: "Configure target",
            description: "Define the target column.",
            run_scope: null,
            step_id: "target-definition",
            action_target: null,
          },
          blockers: [],
          step_guidance: {},
          report_readiness: null,
          branch_id: "br_default",
          run_id: null,
        }),
      ),
    );

    // Import TopBar and render with mocked data
    const { TopBar } = await import("../TopBar");
    renderWithClient(
      <TopBar
        project={{
          project_id: "prj1",
          path: "/tmp",
          name: "Test",
          created_at: "2026-01-01T00:00:00Z",
          schema_family: "cardre.project_store.v2",
          schema_version: 5,
          plan_count: 1,
          run_count: 0,
        }}
        planName="Scorecard Pathway"
        running={false}
        guidance={{
          phase: "build",
          next_action: {
            kind: "configure_step",
            label: "Configure target",
            description: "Define the target column.",
            run_scope: null,
            step_id: "target-definition",
            action_target: null,
          },
          blockers: [],
          step_guidance: {},
          report_readiness: null,
          branch_id: "br_default",
          run_id: null,
          degraded: false,
          diagnostics: [],
        }}
        onAction={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Configure target")).toBeInTheDocument();
    });
  });
});
