import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import { ArtifactPreviewPane } from "../ArtifactPreviewPane";

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("ArtifactPreviewPane recovery", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows recovery banner on API error instead of null", async () => {
    vi.spyOn(api, "getProjectArtifactPreview").mockRejectedValue(
      new ApiError(0, {
        code: "SIDECAR_UNREACHABLE",
        message: "Could not reach the Cardre sidecar.",
      }),
    );

    renderWithClient(
      <ArtifactPreviewPane
        projectId="prj1"
        artifactId="art1"
        mediaType="application/vnd.apache.parquet"
        rowCount={100}
        summaryPreview={null}
      />,
    );

    // Click to show preview
    const showButton = screen.getByText("Show Data Preview");
    showButton.click();

    expect(await screen.findByText("Can't reach the Cardre engine")).toBeInTheDocument();
  });

  it("shows retry button on error", async () => {
    const spy = vi.spyOn(api, "getProjectArtifactPreview").mockRejectedValue(
      new ApiError(0, {
        code: "SIDECAR_UNREACHABLE",
        message: "Down",
      }),
    );

    renderWithClient(
      <ArtifactPreviewPane
        projectId="prj1"
        artifactId="art1"
        mediaType="application/vnd.apache.parquet"
        rowCount={100}
        summaryPreview={null}
      />,
    );

    const showButton = screen.getByText("Show Data Preview");
    showButton.click();

    expect(await screen.findByText("Retry")).toBeInTheDocument();

    // Click retry — should refetch
    const retryButton = screen.getByText("Retry");
    retryButton.click();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("still renders unsupported media type message when no error", () => {
    renderWithClient(
      <ArtifactPreviewPane
        projectId="prj1"
        artifactId="art1"
        mediaType="text/csv"
        rowCount={null}
        summaryPreview={null}
      />,
    );

    expect(screen.getByText(/Preview not supported/)).toBeInTheDocument();
  });
});
