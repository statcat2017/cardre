import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api, ApiError } from "../../../api/client";
import { RunHistoryTab } from "../RunHistoryTab";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("RunHistoryTab recovery", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows RecoveryBanner on API error instead of 'not executed'", async () => {
    vi.spyOn(api, "getProjectRunSteps").mockRejectedValue(
      new ApiError(0, {
        code: "SIDECAR_UNREACHABLE",
        message: "Down",
      }),
    );

    renderWithClient(
      <RunHistoryTab stepId="import" projectId="prj1" runId="run1" tab="history" />,
    );

    await waitFor(() => {
      expect(screen.getByText("Can't reach the Cardre engine")).toBeInTheDocument();
    });
  });

  it("still shows 'not executed' message when query succeeds but no matching steps", async () => {
    vi.spyOn(api, "getProjectRunSteps").mockResolvedValue({
      run_id: "run1",
      steps: [],
    });

    renderWithClient(
      <RunHistoryTab stepId="import" projectId="prj1" runId="run1" tab="history" />,
    );

    await waitFor(() => {
      expect(
        screen.getByText("This step was not executed in the current run."),
      ).toBeInTheDocument();
    });
  });

  it("still shows 'no run' message when runId is null", () => {
    renderWithClient(
      <RunHistoryTab stepId="import" projectId="prj1" runId={null} tab="history" />,
    );

    expect(screen.getByText(/No run yet/)).toBeInTheDocument();
  });
});
