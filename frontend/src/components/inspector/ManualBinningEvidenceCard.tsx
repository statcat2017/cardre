import React from "react";
import { useManualBinningState } from "../../hooks/useManualBinningState";
import { theme } from "../../styles";

interface Props {
  projectId: string;
  planId: string;
  stepId: string;
}

export function ManualBinningEvidenceCard({ projectId, planId, stepId }: Props) {
  const { data: state, isLoading, isError } = useManualBinningState(projectId, planId, stepId);

  if (isLoading) {
    return (
      <div
        style={{
          padding: 12,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          fontSize: 11,
          color: theme.muted,
        }}
      >
        Loading review state…
      </div>
    );
  }

  if (isError || !state) {
    return (
      <div
        style={{
          padding: 12,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          fontSize: 11,
          color: theme.redText,
        }}
      >
        Could not load manual-binning review state.
      </div>
    );
  }

  if (!state.ready) {
    return (
      <div
        style={{
          padding: 12,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          fontSize: 11,
          color: theme.muted,
        }}
      >
        Manual binning not yet available — run the pathway first.
      </div>
    );
  }

  const totalVars = state.variable_summaries?.length ?? 0;
  const editedVars = state.variable_summaries?.filter((v) => v.edited).length ?? 0;
  const reviewedVars = state.variable_summaries?.filter((v) => !v.review_required).length ?? 0;
  const warningCount = state.warnings?.length ?? 0;
  const blockerCount = state.blocking_issues?.length ?? 0;
  const isReviewed = state.review_status === "reviewed";
  const isAccepted = state.review_status === "accepted_automated";

  const statusColor = isReviewed || isAccepted ? theme.greenBg : theme.yellowBg;
  const statusTextColor = isReviewed || isAccepted ? theme.greenText : theme.yellowText;
  const statusLabel = isAccepted
    ? "Automated bins accepted"
    : isReviewed
      ? "Review complete"
      : "Not reviewed";

  return (
    <div
      style={{
        padding: 12,
        border: `1px solid ${theme.border}`,
        borderRadius: 8,
        backgroundColor: theme.surfaceMuted,
        fontSize: 12,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 600, color: theme.text }}>Manual binning review</span>
        <span
          style={{
            padding: "2px 8px",
            borderRadius: 4,
            fontSize: 10,
            fontWeight: 500,
            backgroundColor: statusColor,
            color: statusTextColor,
          }}
        >
          {statusLabel}
        </span>
      </div>

      <div style={{ color: theme.textSoft, fontSize: 11, lineHeight: 1.4 }}>
        {reviewedVars} of {totalVars} variables reviewed · {editedVars} edited
        {warningCount > 0 && ` · ${warningCount} warning${warningCount !== 1 ? "s" : ""}`}
        {blockerCount > 0 && ` · ${blockerCount} blocker${blockerCount !== 1 ? "s" : ""}`}
      </div>

      {isReviewed && state.reviewed_by && (
        <div style={{ fontSize: 10, color: theme.muted }}>
          Reviewer: <strong>{state.reviewed_by}</strong>
          {state.reviewed_at && <> · {new Date(state.reviewed_at).toLocaleString()}</>}
        </div>
      )}

      {state.review_reason && (
        <div style={{ fontSize: 10, color: theme.muted }}>Reason: {state.review_reason}</div>
      )}
    </div>
  );
}
