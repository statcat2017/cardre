import React from "react";
import type { ReportReadinessResponse } from "../types";
import { theme } from "../styles";

interface ReadinessPanelProps {
  targetBranchId: string | null;
  latestRunId: string | null;
  branchName: string | null;
  reportMode: string;
  readinessData: ReportReadinessResponse | undefined;
  readinessLoading: boolean;
  readinessIsFetching: boolean;
  readinessError: Error | null;
  onStepSelect?: (stepId: string) => void;
  onRecheck: () => void;
}

const isLoading = (loading: boolean, fetching: boolean) => loading || fetching;

export function ReadinessPanel({
  targetBranchId,
  latestRunId,
  branchName,
  reportMode,
  readinessData,
  readinessLoading,
  readinessIsFetching,
  readinessError,
  onStepSelect,
  onRecheck,
}: ReadinessPanelProps) {
  if (!targetBranchId) {
    return (
      <div style={{ fontSize: 13, color: theme.muted, padding: "12px 0" }}>Select a branch.</div>
    );
  }

  if (!latestRunId) {
    return (
      <div style={{ fontSize: 13, color: theme.muted, padding: "12px 0" }}>
        No successful run yet.
      </div>
    );
  }

  if (isLoading(readinessLoading, readinessIsFetching)) {
    return (
      <div>
        <div style={{ fontSize: 11, color: theme.muted, padding: "0 4px 8px" }}>
          Checking readiness…
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={onRecheck}
            disabled
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: `1px solid ${theme.border}`,
              fontSize: 13,
              backgroundColor: theme.surfaceMuted,
              cursor: "pointer",
              fontWeight: 500,
              color: theme.textSoft,
              opacity: 0.5,
            }}
          >
            Checking…
          </button>
        </div>
      </div>
    );
  }

  if (readinessError) {
    return (
      <div>
        <div
          style={{
            padding: 12,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            backgroundColor: theme.redBg,
            fontSize: 13,
            color: theme.redText,
          }}
        >
          <strong>Readiness check failed.</strong>{" "}
          {readinessError instanceof Error ? readinessError.message : "Unknown error"}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
          <RecheckButton loading={false} onClick={onRecheck} />
        </div>
      </div>
    );
  }

  if (!readinessData) {
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <RecheckButton loading={false} onClick={onRecheck} />
      </div>
    );
  }

  const isReady = readinessData.ready;
  const hasBlockers = (readinessData.blockers ?? []).length > 0;
  const hasWarnings = (readinessData.warnings ?? []).length > 0;

  return (
    <div>
      {/* Freshness copy — prefer response echo fields */}
      <div style={{ fontSize: 11, color: theme.muted, padding: "0 4px 8px" }}>
        Readiness checked for branch{" "}
        {readinessData.target_branch_id || branchName || targetBranchId} using run{" "}
        {(readinessData.run_id || latestRunId).slice(0, 8)} &middot;{" "}
        {readinessData.report_mode || reportMode} mode.
        {readinessData.checked_at && <span> Last checked {readinessData.checked_at}.</span>}
      </div>

      {/* Result panel */}
      <div
        style={{
          padding: 16,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          backgroundColor: !isReady
            ? theme.redBg
            : hasWarnings
              ? theme.yellowBg
              : theme.surfaceMuted,
        }}
      >
        {!hasBlockers && (
          <div
            style={{
              fontSize: 13,
              color: hasWarnings ? theme.yellowText : theme.greenText,
              marginBottom: hasWarnings ? 8 : 0,
            }}
          >
            <strong>Ready.</strong> All evidence available. Ready to generate.
          </div>
        )}
        {readinessData.blockers?.map((b) => (
          <div
            key={b.code}
            style={{
              padding: "4px 0",
              fontSize: 13,
              color: theme.redText,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <strong style={{ marginRight: 4 }}>Blocked</strong>
            <strong>{b.code}:</strong> {b.message}
            {b.step_id && onStepSelect && (
              <button
                onClick={() => onStepSelect(b.step_id!)}
                style={{
                  padding: "2px 8px",
                  borderRadius: 4,
                  border: `1px solid ${theme.border}`,
                  backgroundColor: theme.surface,
                  color: theme.textSoft,
                  fontSize: 10,
                  cursor: "pointer",
                  marginLeft: "auto",
                  whiteSpace: "nowrap",
                }}
              >
                Go to step
              </button>
            )}
          </div>
        ))}
        {readinessData.warnings?.map((w) => (
          <div key={w.code} style={{ padding: "4px 0", fontSize: 13, color: theme.yellowText }}>
            <strong style={{ marginRight: 8 }}>Warning</strong>
            <strong>{w.code}:</strong> {w.message}
          </div>
        ))}
      </div>

      {/* Recheck button */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <RecheckButton loading={false} onClick={onRecheck} />
      </div>
    </div>
  );
}

function RecheckButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        padding: "8px 16px",
        borderRadius: 6,
        border: `1px solid ${theme.border}`,
        fontSize: 13,
        backgroundColor: theme.surfaceMuted,
        cursor: "pointer",
        fontWeight: 500,
        color: theme.textSoft,
        opacity: loading ? 0.5 : 1,
      }}
    >
      {loading ? "Checking…" : "Re-check readiness"}
    </button>
  );
}
