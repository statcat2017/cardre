import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunListItem } from "../types";

interface Props {
  projectId: string;
}

const ST: Record<string, { bg: string; color: string; label: string }> = {
  succeeded: { bg: "#dcfce7", color: "#166534", label: "Succeeded" },
  failed: { bg: "#fef2f2", color: "#dc2626", label: "Failed" },
  running: { bg: "#fef9c3", color: "#854d0e", label: "Running" },
  cancelled: { bg: "#f3f4f6", color: "#6b7280", label: "Cancelled" },
};

function RunBadge({ status }: { status: string }) {
  const s = ST[status] || ST.failed;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "1px 8px",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: s.bg,
        color: s.color,
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
    <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Run History</h3>

      {isLoading && <div style={{ color: "#64748b", fontSize: 13 }}>Loading runs...</div>}
      {isError && (
        <div style={{ color: "#dc2626", fontSize: 13 }}>
          Failed to load runs: {(error as Error)?.message || "Unknown error"}
        </div>
      )}

      {!isLoading && !isError && runs.length === 0 && (
        <div style={{ color: "#64748b", fontSize: 13 }}>
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
              borderBottom: "2px solid #e2e8f0",
              fontSize: 11,
              fontWeight: 600,
              color: "#64748b",
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
                border: "1px solid #e2e8f0",
                borderRadius: 4,
                backgroundColor: "#fff",
                fontSize: 12,
                alignItems: "center",
              }}
            >
              <span style={{ fontFamily: "monospace", fontSize: 11, color: "#475569" }}>
                {run.run_id.slice(0, 8)}…
              </span>
              <RunBadge status={run.status} />
              <span style={{ fontSize: 11, color: "#64748b" }}>
                {run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
              </span>
              <span style={{ fontSize: 11, color: "#64748b" }}>
                {run.finished_at ? new Date(run.finished_at).toLocaleString() : "—"}
              </span>
              <span style={{ fontSize: 12, color: "#1e293b", fontWeight: 500 }}>
                {run.step_count}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
