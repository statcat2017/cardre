import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ArtifactPreviewPane } from "./ArtifactPreviewPane";
import { RecoveryBanner } from "./RecoveryBanner";
import { theme } from "../styles";

interface Props {
  projectId: string;
  artifactId: string;
}

export function ArtifactSummaryInline({ projectId, artifactId }: Props) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["artifactSummary", projectId, artifactId],
    queryFn: () => api.getProjectArtifactSummary(projectId, artifactId),
    enabled: !!artifactId,
  });

  if (isLoading)
    return <div style={{ padding: 8, fontSize: 12, color: theme.muted }}>Loading summary...</div>;
  if (isError) return <RecoveryBanner error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  const metaRows: [string, string | number | null][] = [
    ["Role", data.role],
    ["Type", data.artifact_type],
    ["Media Type", data.media_type],
    ["Rows", data.row_count ?? null],
    ["Columns", data.column_count ?? null],
  ];

  return (
    <div
      style={{
        marginLeft: 16,
        marginTop: 4,
        padding: "8px 12px",
        border: `1px solid ${theme.border}`,
        borderRadius: 4,
        backgroundColor: theme.surfaceMuted,
        fontSize: 11,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, color: theme.text, fontSize: 12 }}>
        Summary
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
        {metaRows.map(([label, val]) => (
          <div key={label}>
            <span style={{ color: theme.muted }}>{label}: </span>
            <span style={{ color: theme.text, fontWeight: 500 }}>{val ?? "—"}</span>
          </div>
        ))}
      </div>
      <ArtifactPreviewPane
        projectId={projectId}
        artifactId={data.artifact_id}
        mediaType={data.media_type}
        rowCount={data.row_count}
        summaryPreview={data.summary_preview}
      />
    </div>
  );
}
