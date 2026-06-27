import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { ArtifactSummaryResponse } from "../../types";
import { ArtifactSummaryInline } from "../ArtifactSummaryInline";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const MOCK_SUMMARY: ArtifactSummaryResponse = {
  artifact_id: "art1",
  artifact_type: "dataset",
  role: "input",
  media_type: "application/vnd.apache.parquet",
  logical_hash: "h",
  physical_hash: "p",
  row_count: 10,
  column_count: 2,
  summary_preview: null,
};

describe("ArtifactSummaryInline", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls project-scoped getProjectArtifactSummary", async () => {
    const spy = vi.spyOn(api, "getProjectArtifactSummary").mockResolvedValue(MOCK_SUMMARY);

    renderWithClient(
      <ArtifactSummaryInline projectId="prj1" artifactId="art1" />,
    );

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith("prj1", "art1");
    });
  });
});
