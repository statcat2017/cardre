import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { theme } from "../../styles";

interface Props {
  stepId: string;
  projectId: string;
  runId: string | null;
  tab: string;
}

export function RunHistoryTab({ stepId, projectId, runId, tab }: Props) {
  const { data: runData } = useQuery({
    queryKey: ["projectRuns", projectId],
    queryFn: () => api.getProjectRuns(projectId),
    enabled: tab === "history",
  });

  if (!runData?.runs?.length) {
    return <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>No runs yet.</div>;
  }

  const relevantRuns = runData.runs.filter((r) => !runId || r.run_id === runId).slice(0, 5);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {relevantRuns.map((r) => (
        <div
          key={r.run_id}
          style={{
            padding: 8, border: `1px solid ${theme.border}`, borderRadius: 4,
            backgroundColor: theme.surface, fontSize: 11,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <code style={{ color: theme.text, fontFamily: theme.fontMono, fontSize: 10 }}>
              {r.run_id.slice(0, 8)}…
            </code>
            <span style={{
              fontWeight: 600, fontSize: 10,
              color: r.status === "succeeded" ? theme.greenText : r.status === "failed" ? theme.redText : theme.yellowText,
            }}>
              {r.status}
            </span>
          </div>
          {r.finished_at && (
            <div style={{ color: theme.muted, fontSize: 10, marginTop: 2 }}>
              {new Date(r.finished_at).toLocaleDateString()}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
