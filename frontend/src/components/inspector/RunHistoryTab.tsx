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
  const { data: runStepsData, isLoading } = useQuery({
    queryKey: ["runSteps", runId],
    queryFn: () => api.getRunSteps(runId!),
    enabled: !!runId && tab === "history",
    retry: false,
  });

  // For the current run, show all step records that include this step_id.
  // If runId is not available, show nothing (no run yet).
  if (!runId) {
    return <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>No run yet — run the pathway to see step execution history.</div>;
  }

  if (isLoading) {
    return <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>Loading run history...</div>;
  }

  const stepsForThisStep = runStepsData?.steps?.filter((s) => s.step_id === stepId) ?? [];

  if (stepsForThisStep.length === 0) {
    return <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>This step was not executed in the current run.</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {stepsForThisStep.map((rs) => (
        <div
          key={rs.run_step_id || rs.step_id}
          style={{
            padding: 8, border: `1px solid ${theme.border}`, borderRadius: 4,
            backgroundColor: theme.surface, fontSize: 11,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontWeight: 600, fontSize: 10, color: theme.text }}>
              {rs.step_id}
            </span>
            <span style={{
              fontWeight: 600, fontSize: 10,
              color: rs.status === "succeeded" ? theme.greenText : rs.status === "failed" ? theme.redText : theme.yellowText,
            }}>
              {rs.status}
            </span>
          </div>
          {rs.is_carried_forward && (
            <div style={{ color: theme.blueText, fontSize: 10, marginTop: 2 }}>Carried forward</div>
          )}
          {rs.finished_at && (
            <div style={{ color: theme.muted, fontSize: 10, marginTop: 2 }}>
              {new Date(rs.finished_at).toLocaleDateString()}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
