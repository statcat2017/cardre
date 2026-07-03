/**
 * Minimal manual-binning editor spike.
 *
 * Variable list, bin grid, WOE/IV preview, warnings panel,
 * reviewer notes, approve/reject.
 */

import React, { useState } from "react";
import { useManualBinningReview } from "../hooks/useManualBinningReview";
import type { components } from "../api/schema.d";

export interface ManualBinningEditorSpikeProps {
  baseUrl: string;
  projectId: string;
  planVersionId: string;
  stepId: string;
}

export function ManualBinningEditorSpike({
  baseUrl,
  projectId,
  planVersionId,
  stepId,
}: ManualBinningEditorSpikeProps) {
  const { review, loading, error, submitEdit, updateReview, loadReview, clearError } =
    useManualBinningReview({ baseUrl, projectId });

  const [overrides] = useState<Record<string, unknown>[]>([]);
  const [reviewerNotes, setReviewerNotes] = useState("");
  const [status, setStatus] = useState("pending");
  const [result, setResult] = useState<string | null>(null);

  const handleSubmitEdit = async () => {
    clearError();
    setResult(null);
    try {
      const request: components["schemas"]["ManualBinningEditRequest"] = {
        plan_version_id: planVersionId,
        step_id: stepId,
        overrides,
        reviewer_notes: reviewerNotes,
        status,
        affected_downstream_step_ids: [],
      };
      const response = await submitEdit(request);
      setResult(
        `Edit applied: new plan version ${response.new_plan_version_id}, review ${response.review_id}`,
      );
      // Auto-load the review so approve/reject buttons become active
      await loadReview(response.review_id);
    } catch {
      // error is set by the hook
    }
  };

  const handleApprove = async () => {
    if (!review) return;
    clearError();
    try {
      await updateReview(review.review_id, { status: "approved", reviewer_notes: reviewerNotes });
      setResult("Review approved.");
    } catch {
      // error is set by the hook
    }
  };

  const handleReject = async () => {
    if (!review) return;
    clearError();
    try {
      await updateReview(review.review_id, { status: "rejected", reviewer_notes: reviewerNotes });
      setResult("Review rejected.");
    } catch {
      // error is set by the hook
    }
  };

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1rem", maxWidth: "800px" }}>
      <h2>Manual Binning Editor</h2>

      {/* Error display */}
      {error && (
        <div
          style={{
            background: "#fee",
            border: "1px solid #f99",
            borderRadius: "4px",
            padding: "0.5rem",
            marginBottom: "1rem",
          }}
        >
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Result display */}
      {result && (
        <div
          style={{
            background: "#efe",
            border: "1px solid #9f9",
            borderRadius: "4px",
            padding: "0.5rem",
            marginBottom: "1rem",
          }}
        >
          {result}
        </div>
      )}

      {/* Variable list placeholder */}
      <section style={{ marginBottom: "1rem" }}>
        <h3>Variables</h3>
        <p style={{ color: "#666", fontStyle: "italic" }}>
          Variable list will appear here once evidence is available.
        </p>
      </section>

      {/* Bin grid placeholder */}
      <section style={{ marginBottom: "1rem" }}>
        <h3>Bin Grid</h3>
        <p style={{ color: "#666", fontStyle: "italic" }}>
          Bin grid with WOE/IV preview will appear here once evidence is available.
        </p>
      </section>

      {/* WOE/IV preview placeholder */}
      <section style={{ marginBottom: "1rem" }}>
        <h3>WOE / IV Preview</h3>
        <p style={{ color: "#666", fontStyle: "italic" }}>
          Preview panel will render after selecting a variable.
        </p>
      </section>

      {/* Warnings panel placeholder */}
      <section style={{ marginBottom: "1rem" }}>
        <h3>Warnings</h3>
        <p style={{ color: "#666", fontStyle: "italic" }}>
          Warnings will appear here when present.
        </p>
      </section>

      {/* Reviewer notes */}
      <section style={{ marginBottom: "1rem" }}>
        <h3>Reviewer Notes</h3>
        <textarea
          value={reviewerNotes}
          onChange={(e) => setReviewerNotes(e.target.value)}
          placeholder="Enter review notes..."
          rows={3}
          style={{
            width: "100%",
            padding: "0.5rem",
            borderRadius: "4px",
            border: "1px solid #ccc",
          }}
        />
      </section>

      {/* Action buttons */}
      <section style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <label>
          Status:{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </label>

        <button
          onClick={handleSubmitEdit}
          disabled={loading}
          style={{
            padding: "0.5rem 1rem",
            background: "#0066cc",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Submitting..." : "Submit Edit"}
        </button>

        <button
          onClick={handleApprove}
          disabled={loading || !review}
          style={{
            padding: "0.5rem 1rem",
            background: "#090",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: loading || !review ? "not-allowed" : "pointer",
          }}
        >
          Approve
        </button>

        <button
          onClick={handleReject}
          disabled={loading || !review}
          style={{
            padding: "0.5rem 1rem",
            background: "#c00",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            cursor: loading || !review ? "not-allowed" : "pointer",
          }}
        >
          Reject
        </button>
      </section>

      {/* Current review state */}
      {review && (
        <section
          style={{
            marginTop: "1rem",
            padding: "0.5rem",
            background: "#f5f5f5",
            borderRadius: "4px",
          }}
        >
          <h4>Current Review</h4>
          <pre>{JSON.stringify(review, null, 2)}</pre>
        </section>
      )}
    </div>
  );
}
