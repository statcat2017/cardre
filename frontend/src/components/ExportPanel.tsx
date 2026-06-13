import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  projectId: string;
}

export function ExportPanel({ projectId }: Props) {
  const { data: projectRuns } = useQuery({
    queryKey: ["projectRuns", projectId],
    queryFn: () => api.getProjectRuns(projectId),
    enabled: !!projectId,
  });

  const successfulRuns = projectRuns?.runs?.filter((r) => r.status === "succeeded") ?? [];

  return (
    <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Export Evidence</h3>

      <div
        style={{
          padding: 16,
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          backgroundColor: "#fff",
          marginBottom: 12,
        }}
      >
        <h4 style={{ fontSize: 13, fontWeight: 600, margin: "0 0 8px 0" }}>
          Technical Manifest Export
        </h4>
        <p style={{ fontSize: 12, color: "#64748b", margin: "0 0 12px 0" }}>
          The technical manifest bundles the full audit trail: plan steps, run evidence,
          artefact hashes, and node execution fingerprints into a ZIP archive suitable
          for model governance and audit submission.
        </p>
        <div style={{ fontSize: 12, color: "#475569", marginBottom: 8 }}>
          <strong>{successfulRuns.length}</strong> successful run
          {successfulRuns.length !== 1 ? "s" : ""} completed for this project.
        </div>
        {successfulRuns.length === 0 && (
          <div
            style={{
              padding: "8px 12px",
              backgroundColor: "#fffbeb",
              border: "1px solid #fde68a",
              borderRadius: 4,
              color: "#92400e",
              fontSize: 12,
            }}
          >
            Run the Scorecard Pathway to completion before exporting. All build,
            validation, and cutoff steps must succeed for a complete manifest.
          </div>
        )}
        {successfulRuns.length > 0 && (
          <div
            style={{
              padding: "8px 12px",
              backgroundColor: "#f0fdf4",
              border: "1px solid #bbf7d0",
              borderRadius: 4,
              color: "#166534",
              fontSize: 12,
            }}
          >
            Manifest export will be available from the Tauri menu or a future
            CLI command. The artefact store already contains all required
            evidence files.
          </div>
        )}
      </div>

      <div
        style={{
          padding: 16,
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          backgroundColor: "#fff",
        }}
      >
        <h4 style={{ fontSize: 13, fontWeight: 600, margin: "0 0 8px 0" }}>Recent Runs</h4>
        {successfulRuns.length === 0 ? (
          <div style={{ fontSize: 12, color: "#94a3b8" }}>No successful runs yet.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {successfulRuns.slice(0, 5).map((run) => (
              <div
                key={run.run_id}
                style={{
                  padding: "6px 8px",
                  border: "1px solid #e2e8f0",
                  borderRadius: 4,
                  backgroundColor: "#f8fafc",
                  fontSize: 11,
                  color: "#475569",
                }}
              >
                <span style={{ fontFamily: "monospace" }}>{run.run_id.slice(0, 8)}…</span>
                {run.finished_at && (
                  <span style={{ marginLeft: 12, color: "#94a3b8" }}>
                    finished {new Date(run.finished_at).toLocaleString()}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
