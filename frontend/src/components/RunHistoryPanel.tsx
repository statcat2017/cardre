import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunListItem } from "../types";
import { theme } from "../styles";

interface Props {
  projectId: string;
}

const ST: Record<string, { bg: string; color: string; label: string }> = {
  succeeded: { bg: theme.greenBg, color: theme.greenText, label: "Succeeded" },
  failed: { bg: theme.redBg, color: theme.redText, label: "Failed" },
  running: { bg: theme.yellowBg, color: theme.yellowText, label: "Running" },
  cancelled: { bg: theme.canvasSoft, color: theme.muted, label: "Cancelled" },
};

function RunBadge({ status }: { status: string }) {
  const s = ST[status] || ST.failed;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "1px 8px",
        borderRadius: 9999,
        fontSize: 10,
        fontWeight: 600,
        backgroundColor: s.bg,
        color: s.color,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}
    >
      {s.label}
    </span>
  );
}

export function RunHistoryPanel({ projectId }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["projectRuns", projectId],
    queryFn: () => api.getProjectRuns(projectId),
    enabled: !!projectId,
  });

  const runs: RunListItem[] = data?.runs ?? [];

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: theme.text }}>
        Run History
      </h3>

      {isLoading && <div style={{ color: theme.muted, fontSize: 13 }}>Loading runs...</div>}
      {isError && (
        <div style={{ color: theme.redText, fontSize: 13 }}>
          Failed to load runs: {(error as Error)?.message || "Unknown error"}
        </div>
      )}

      {!isLoading && !isError && runs.length === 0 && (
        <div style={{ color: theme.muted, fontSize: 13 }}>
          No runs yet. Import a dataset and run the pathway to see results here.
        </div>
      )}

      {runs.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 80px 130px 130px 70px",
              gap: 8,
              padding: "6px 8px",
              borderBottom: `1px solid ${theme.border}`,
              fontSize: 11,
              fontWeight: 600,
              color: theme.muted,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            <span>Run ID</span>
            <span>Status</span>
            <span>Started</span>
            <span>Finished</span>
            <span>Steps</span>
          </div>
          {runs.map((run) => (
            <div
              key={run.run_id}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 80px 130px 130px 70px",
                gap: 8,
                padding: "8px",
                border: `1px solid ${theme.border}`,
                borderRadius: 4,
                backgroundColor: theme.surface,
                fontSize: 12,
                alignItems: "center",
              }}
            >
              <span style={{ fontFamily: theme.fontMono, fontSize: 11, color: theme.textSoft }}>
                {run.run_id.slice(0, 8)}…
              </span>
              <RunBadge status={run.status} />
              <span style={{ fontSize: 11, color: theme.muted }}>
                {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
              </span>
              <span style={{ fontSize: 11, color: theme.muted }}>
                {run.finished_at ? new Date(run.finished_at).toLocaleString() : "—"}
              </span>
              <span style={{ fontSize: 12, color: theme.text, fontWeight: 500 }}>
                {run.step_count}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
