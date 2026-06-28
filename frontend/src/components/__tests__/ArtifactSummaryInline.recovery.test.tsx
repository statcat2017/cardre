import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { ArtifactSummaryInline } from "../ArtifactSummaryInline";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ArtifactSummaryInline recovery", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows recovery banner on API error instead of null", async () => {
    vi.spyOn(api, "getProjectArtifactSummary").mockRejectedValue(
      new ApiError(404, {
        code: "ARTIFACT_NOT_FOUND",
        message: "No artifact with ID art1 in project prj1",
      }),
    );

    renderWithClient(<ArtifactSummaryInline projectId="prj1" artifactId="art1" />);

    await waitFor(() => {
      expect(screen.getByText("Artifact not found")).toBeInTheDocument();
    });
  });

  it("shows retry button on error", async () => {
    const spy = vi.spyOn(api, "getProjectArtifactSummary").mockRejectedValue(
      new ApiError(0, {
        code: "SIDECAR_UNREACHABLE",
        message: "Down",
      }),
    );

    renderWithClient(<ArtifactSummaryInline projectId="prj1" artifactId="art1" />);

    await waitFor(() => {
      expect(screen.getByText("Retry")).toBeInTheDocument();
    });

    spy.mockReset();
    spy.mockResolvedValue({
      artifact_id: "art1",
      artifact_type: "dataset",
      role: "input",
      media_type: "application/vnd.apache.parquet",
      logical_hash: "h",
      physical_hash: "p",
      row_count: 10,
      column_count: 2,
      summary_preview: null,
    });

    screen.getByText("Retry").click();
    await waitFor(() => {
      expect(screen.getByText("input")).toBeInTheDocument();
    });
  });

  it("still renders summary on success", async () => {
    vi.spyOn(api, "getProjectArtifactSummary").mockResolvedValue({
      artifact_id: "art1",
      artifact_type: "dataset",
      role: "input",
      media_type: "application/vnd.apache.parquet",
      logical_hash: "h",
      physical_hash: "p",
      row_count: 10,
      column_count: 2,
      summary_preview: null,
    });

    renderWithClient(<ArtifactSummaryInline projectId="prj1" artifactId="art1" />);

    await waitFor(() => {
      expect(screen.getByText("input")).toBeInTheDocument();
    });
  });
});
