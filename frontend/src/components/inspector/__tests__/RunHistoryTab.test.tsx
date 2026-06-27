import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../../../api/client";
import type { RunStepsResponse } from "../../../types";
import { RunHistoryTab } from "../RunHistoryTab";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const MOCK_STEPS: RunStepsResponse = {
  run_id: "run1",
  steps: [],
};

describe("RunHistoryTab", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls project-scoped getProjectRunSteps", async () => {
    const spy = vi.spyOn(api, "getProjectRunSteps").mockResolvedValue(MOCK_STEPS);

    renderWithClient(<RunHistoryTab stepId="import" projectId="prj1" runId="run1" tab="history" />);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith("prj1", "run1");
    });
  });
});
