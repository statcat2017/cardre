import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { theme } from "../../styles";

interface Props {
  runId: string | null;
  stepId: string;
  projectId: string;
  tab: string;
}

export function EvidenceTab({ runId, stepId, projectId, tab }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["stepEvidence", runId, stepId],
    queryFn: () => api.getStepEvidence(runId!, stepId, projectId),
    enabled: !!runId && tab === "evidence",
    retry: false,
  });

  if (!runId) {
    return <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>No run evidence yet — run the pathway to produce evidence.</div>;
  }

  if (isLoading) {
    return <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>Loading evidence...</div>;
  }

  if (!data || !data.items || data.items.length === 0) {
    return <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>No evidence artifacts for this step.</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {data.items.map((item) => (
        <div
          key={item.artifact_id}
          style={{
            padding: 10, border: `1px solid ${theme.border}`, borderRadius: 6,
            backgroundColor: theme.surfaceMuted, fontSize: 11,
          }}
        >
          <div style={{ fontWeight: 600, color: theme.text, marginBottom: 2 }}>
            {item.evidence_kind || item.artifact_type}
          </div>
          <div style={{ color: theme.muted, fontFamily: theme.fontMono, fontSize: 10 }}>
            {item.artifact_id.slice(0, 12)}…
          </div>
          {item.logical_hash && (
            <div style={{ color: theme.muted, fontSize: 10 }}>hash: {item.logical_hash.slice(0, 12)}…</div>
          )}
          <div style={{ color: theme.mutedSoft, fontSize: 10 }}>{item.media_type}</div>
        </div>
      ))}
    </div>
  );
}
