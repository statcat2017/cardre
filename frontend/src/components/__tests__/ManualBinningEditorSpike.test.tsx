/**
 * Tests for the ManualBinningEditorSpike component.
 *
 * These tests verify the full edit-to-review cycle against a mock API.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ManualBinningEditorSpike } from "../ManualBinningEditorSpike";

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const BASE_URL = "http://localhost:8752";
const PROJECT_ID = "proj-001";
const PLAN_VERSION_ID = "pv-001";
const STEP_ID = "manual-binning";

const REVIEW_ID = "review-001";

const reviewData = {
  review_id: REVIEW_ID,
  plan_version_id: "pv-002",
  step_id: "manual-binning",
  status: "pending",
  reviewer_notes: "",
  affected_downstream_step_ids: [],
  created_at: "2025-01-01T00:00:00",
  updated_at: "2025-01-01T00:00:00",
};

const approvedReviewData = {
  ...reviewData,
  status: "approved",
  reviewer_notes: "Looks good.",
};

const rejectedReviewData = {
  ...reviewData,
  status: "rejected",
  reviewer_notes: "Need changes.",
};

const handlers = [
  // POST /edit
  http.post(
    `${BASE_URL}/projects/${PROJECT_ID}/manual-binning/edit`,
    async () => {
      return HttpResponse.json({
        new_plan_version_id: "pv-002",
        review_id: REVIEW_ID,
        affected_step_ids: ["apply-woe"],
      });
    },
  ),

  // GET /reviews/:id
  http.get(
    `${BASE_URL}/projects/${PROJECT_ID}/manual-binning/reviews/:reviewId`,
    async () => {
      return HttpResponse.json(reviewData);
    },
  ),

  // PATCH /reviews/:id
  http.patch(
    `${BASE_URL}/projects/${PROJECT_ID}/manual-binning/reviews/:reviewId`,
    async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({
        ...reviewData,
        status: body.status || "pending",
        reviewer_notes: body.reviewer_notes || "",
      });
    },
  ),
];

const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ManualBinningEditorSpike", () => {
  it("renders the editor with all sections", () => {
    render(
      <ManualBinningEditorSpike
        baseUrl={BASE_URL}
        projectId={PROJECT_ID}
        planVersionId={PLAN_VERSION_ID}
        stepId={STEP_ID}
      />,
    );

    expect(screen.getByText("Manual Binning Editor")).toBeTruthy();
    expect(screen.getByText("Variables")).toBeTruthy();
    expect(screen.getByText("Bin Grid")).toBeTruthy();
    expect(screen.getByText("WOE / IV Preview")).toBeTruthy();
    expect(screen.getByText("Warnings")).toBeTruthy();
    expect(screen.getByText("Reviewer Notes")).toBeTruthy();
    expect(screen.getByText("Submit Edit")).toBeTruthy();
    expect(screen.getByText("Approve")).toBeTruthy();
    expect(screen.getByText("Reject")).toBeTruthy();
  });

  it("submits an edit and displays the result", async () => {
    const user = userEvent.setup();
    render(
      <ManualBinningEditorSpike
        baseUrl={BASE_URL}
        projectId={PROJECT_ID}
        planVersionId={PLAN_VERSION_ID}
        stepId={STEP_ID}
      />,
    );

    // Type reviewer notes
    const notesInput = screen.getByPlaceholderText("Enter review notes...");
    await user.type(notesInput, "Merged low-frequency bins.");

    // Click Submit Edit
    await user.click(screen.getByText("Submit Edit"));

    // Wait for the result message (auto-loads review after submit)
    await waitFor(() => {
      expect(
        screen.getByText(/Edit applied: new plan version pv-002, review review-001/),
      ).toBeTruthy();
    });
  });

  it("approves a review and shows confirmation", async () => {
    const user = userEvent.setup();
    render(
      <ManualBinningEditorSpike
        baseUrl={BASE_URL}
        projectId={PROJECT_ID}
        planVersionId={PLAN_VERSION_ID}
        stepId={STEP_ID}
      />,
    );

    // Submit edit — this now also loads the review (review state populated)
    await user.click(screen.getByText("Submit Edit"));

    // Wait for edit result and review to load
    await waitFor(() => {
      expect(screen.getByText(/Edit applied/)).toBeTruthy();
    });

    // Approve button should now be enabled (review loaded)
    await waitFor(() => {
      expect(screen.getByText("Approve")).not.toBeDisabled();
    });

    // Type reviewer notes
    const notesInput = screen.getByPlaceholderText("Enter review notes...");
    await user.clear(notesInput);
    await user.type(notesInput, "Looks good.");

    // Click Approve
    await user.click(screen.getByText("Approve"));

    await waitFor(() => {
      expect(screen.getByText("Review approved.")).toBeTruthy();
    });
  });

  it("rejects a review and shows confirmation", async () => {
    const user = userEvent.setup();
    render(
      <ManualBinningEditorSpike
        baseUrl={BASE_URL}
        projectId={PROJECT_ID}
        planVersionId={PLAN_VERSION_ID}
        stepId={STEP_ID}
      />,
    );

    // Submit edit to create review and load it
    await user.click(screen.getByText("Submit Edit"));

    await waitFor(() => {
      expect(screen.getByText(/Edit applied/)).toBeTruthy();
    });

    // Reject button should now be enabled
    await waitFor(() => {
      expect(screen.getByText("Reject")).not.toBeDisabled();
    });

    // Click Reject
    const rejectButton = screen.getByText("Reject");
    await user.click(rejectButton);

    await waitFor(() => {
      expect(screen.getByText("Review rejected.")).toBeTruthy();
    });
  });

  it("displays server errors", async () => {
    // Override handler to return an error
    server.use(
      http.post(
        `${BASE_URL}/projects/${PROJECT_ID}/manual-binning/edit`,
        () => {
          return HttpResponse.json(
            {
              detail: {
                code: "PLAN_MUTATION_ERROR",
                message: "Step not found",
              },
            },
            { status: 400 },
          );
        },
      ),
    );

    const user = userEvent.setup();
    render(
      <ManualBinningEditorSpike
        baseUrl={BASE_URL}
        projectId={PROJECT_ID}
        planVersionId={PLAN_VERSION_ID}
        stepId={STEP_ID}
      />,
    );

    await user.click(screen.getByText("Submit Edit"));

    await waitFor(() => {
      expect(screen.getByText(/PLAN_MUTATION_ERROR/)).toBeTruthy();
    });
  });
});
