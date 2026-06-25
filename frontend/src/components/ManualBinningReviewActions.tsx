import React, { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, isApiError } from "../api/client";
import type { ManualBinningEditorStateResponse } from "../types";
import { theme } from "../styles";
import { useMessage } from "../hooks/useMessage";
import { MessageBanner } from "./MessageBanner";

interface Props {
  state: ManualBinningEditorStateResponse;
  planId: string;
  stepId: string;
  basePlanVersionId: string;
  onPlanRefreshed: (detail: { latest_version_id?: string }) => void;
}

const REASON_CODES = [
  { value: "business_interpretability", label: "Business interpretability" },
  { value: "monotonicity", label: "Monotonicity" },
  { value: "sparse_bin", label: "Sparse bin" },
  { value: "zero_cell", label: "Zero cell" },
  { value: "missing_value_treatment", label: "Missing value handling" },
  { value: "special_value_treatment", label: "Special value handling" },
  { value: "regulatory_or_policy", label: "Regulatory or policy" },
  { value: "other", label: "Other" },
];

export function ManualBinningReviewActions({ state, planId, stepId, basePlanVersionId, onPlanRefreshed }: Props) {
  const queryClient = useQueryClient();
  const { msg, msgType, clearMsg, setError, setSuccess, setInfo } = useMessage();
  const [reviewing, setReviewing] = useState(false);
  const [showReasonForm, setShowReasonForm] = useState(false);
  const [reasonCode, setReasonCode] = useState("");
  const [reviewReason, setReviewReason] = useState("");

  const editedCount = state.variable_summaries?.filter((v) => v.edited).length ?? 0;
  const reviewedCount = state.variable_summaries?.filter((v) => !v.review_required).length ?? 0;
  const totalCount = state.variable_summaries?.length ?? 0;
  const warnTotal = state.variable_summaries?.reduce(
    (s, v) => s + (v.zero_cell_warning_count || 0) + (v.sparse_bin_warning_count || 0), 0,
  ) ?? 0;
  const isBlocked = (state.blocking_issues?.length ?? 0) > 0;

  const handleReview = async (acceptAutomated: boolean) => {
    clearMsg();
    setReviewing(true);
    try {
      const resp = await api.reviewManualBinning(planId, stepId, {
        project_id: state.project_id || "",
        plan_version_id: basePlanVersionId,
        step_id: stepId,
        reviewed: !acceptAutomated,
        accept_automated: acceptAutomated,
        ...(acceptAutomated ? {} : { reason_code: reasonCode || undefined, review_reason: reviewReason || undefined }),
      });
      setSuccess(acceptAutomated ? "Automated bins accepted." : "Manual binning review complete.");
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningState", state.project_id, planId, stepId] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState"] });
      queryClient.invalidateQueries({ queryKey: ["workflowGuidance"] });
      queryClient.invalidateQueries({ queryKey: ["reportReadiness"] });
      setShowReasonForm(false);
      setReasonCode("");
      setReviewReason("");
      if (resp.new_plan_version_id) {
        onPlanRefreshed({ latest_version_id: resp.new_plan_version_id });
      }
    } catch (e: unknown) {
      if (isApiError(e) && e.status === 409 && e.detail.code === "STALE_VERSION") {
        setInfo("Plan was modified externally. Refreshing…");
        onPlanRefreshed(e.detail);
      } else {
        setError(isApiError(e) ? e.detail.message : (acceptAutomated ? "Accept failed" : "Review failed"));
      }
    } finally {
      setReviewing(false);
    }
  };

  if (state.review_status === "reviewed" || state.review_status === "accepted_automated") {
    return (
      <div style={{ marginTop: 16, padding: 16, border: `1px solid ${theme.border}`, borderRadius: 8, backgroundColor: theme.greenBg }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: theme.greenText, marginBottom: 8 }}>
          {state.review_status === "accepted_automated" ? "Automated bins accepted" : "Review complete"}
        </div>
        {state.reviewed_by && (
          <div style={{ fontSize: 11, color: theme.textSoft }}>
            Reviewed by <strong>{state.reviewed_by}</strong>
            {state.reviewed_at && <> · {new Date(state.reviewed_at).toLocaleString()}</>}
          </div>
        )}
        {state.review_reason && (
          <div style={{ fontSize: 10, color: theme.muted, marginTop: 4 }}>Reason: {state.review_reason}</div>
        )}
      </div>
    );
  }

  return (
    <div style={{ marginTop: 16 }}>
      <MessageBanner message={msg} type={msgType} />

      <div style={{ padding: 16, border: `1px solid ${theme.border}`, borderRadius: 8, backgroundColor: theme.surfaceMuted }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: theme.text, marginBottom: 4 }}>Bin Review</div>
        <div style={{ fontSize: 11, color: theme.textSoft, marginBottom: 12 }}>
          {reviewedCount} of {totalCount} variables reviewed · {editedCount} edited · {warnTotal} unresolved warnings
        </div>

        {state.blocking_issues && state.blocking_issues.length > 0 && (
          <div style={{ marginBottom: 12, padding: 8, backgroundColor: theme.yellowBg, border: `1px solid ${theme.border}`, borderRadius: 4 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: theme.yellowText, marginBottom: 4 }}>BLOCKING ISSUES</div>
            {(state.blocking_issues as Array<{ code: string; message: string }>).map((bi, i) => (
              <div key={i} style={{ fontSize: 10, color: theme.yellowText, padding: "1px 0" }}>
                <strong>{bi.code}</strong>: {bi.message}
              </div>
            ))}
          </div>
        )}

        {!showReasonForm ? (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              onClick={() => setShowReasonForm(true)}
              disabled={isBlocked}
              style={{
                padding: "8px 16px", borderRadius: 4, border: "none",
                backgroundColor: isBlocked ? theme.mutedSoft : theme.text,
                color: "#fff", fontSize: 12, fontWeight: 600,
                cursor: isBlocked ? "not-allowed" : "pointer",
                opacity: isBlocked ? 0.5 : 1,
              }}
              title={isBlocked ? "Resolve blocking issues first" : "Mark review complete"}
            >
              Mark review complete
            </button>
            <button
              onClick={() => handleReview(true)}
              disabled={reviewing}
              style={{
                padding: "8px 16px", borderRadius: 4,
                border: `1px solid ${theme.border}`,
                backgroundColor: theme.surface, color: theme.textSoft,
                fontSize: 12, fontWeight: 500, cursor: reviewing ? "not-allowed" : "pointer",
              }}
            >
              {reviewing ? "Saving..." : "Accept automated bins"}
            </button>
          </div>
        ) : (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 11, color: theme.text, marginBottom: 8 }}>
              Provide a reason for completing the review.
            </div>
            <div style={{ marginBottom: 8 }}>
              <select
                value={reasonCode}
                onChange={(e) => setReasonCode(e.target.value)}
                style={{
                  width: "100%", padding: "6px 8px", border: `1px solid ${theme.border}`,
                  borderRadius: 4, fontSize: 11, color: theme.text, backgroundColor: theme.surface,
                }}
              >
                <option value="">Select a reason code…</option>
                {REASON_CODES.map((rc) => (
                  <option key={rc.value} value={rc.value}>{rc.label}</option>
                ))}
              </select>
            </div>
            <div style={{ marginBottom: 8 }}>
              <textarea
                value={reviewReason}
                onChange={(e) => setReviewReason(e.target.value)}
                placeholder="Describe why you are marking review complete…"
                rows={2}
                style={{
                  width: "100%", padding: "6px 8px", border: `1px solid ${theme.border}`,
                  borderRadius: 4, fontSize: 11, color: theme.text, backgroundColor: theme.surface,
                  resize: "vertical", boxSizing: "border-box",
                }}
              />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => handleReview(false)}
                disabled={reviewing || !reasonCode || !reviewReason}
                style={{
                  padding: "8px 16px", borderRadius: 4, border: "none",
                  backgroundColor: (!reasonCode || !reviewReason) ? theme.mutedSoft : theme.text,
                  color: "#fff", fontSize: 12, fontWeight: 600,
                  cursor: (!reasonCode || !reviewReason) ? "not-allowed" : "pointer",
                  opacity: (!reasonCode || !reviewReason) ? 0.5 : 1,
                }}
              >
                {reviewing ? "Submitting…" : "Confirm review"}
              </button>
              <button
                onClick={() => { setShowReasonForm(false); setReasonCode(""); setReviewReason(""); }}
                style={{
                  padding: "8px 16px", borderRadius: 4,
                  border: `1px solid ${theme.border}`,
                  backgroundColor: theme.surface, color: theme.textSoft,
                  fontSize: 12, cursor: "pointer",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
