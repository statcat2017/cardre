import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ArtifactPreviewPane } from "./ArtifactPreviewPane";

interface Props {
  artifactId: string;
}

export function ArtifactSummaryInline({ artifactId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["artifactSummary", artifactId],
    queryFn: () => api.getArtifactSummary(artifactId),
    enabled: !!artifactId,
  });

  if (isLoading) return <div style={{ padding: 8, fontSize: 12, color: "#64748b" }}>Loading summary...</div>;
  if (!data) return null;

  const metaRows: [string, string | number | null][] = [
    ["Role", data.role],
    ["Type", data.artifact_type],
    ["Media Type", data.media_type],
    ["Rows", data.row_count ?? null],
    ["Columns", data.column_count ?? null],
  ];

  return (
    <div style={{ marginLeft: 16, marginTop: 4, padding: "8px 12px", border: "1px solid #dbeafe", borderRadius: 4, backgroundColor: "#f8fafc", fontSize: 11 }}>
      <div style={{ fontWeight: 600, marginBottom: 6, color: "#1e293b", fontSize: 12 }}>Summary</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
        {metaRows.map(([label, val]) => (
          <div key={label}>
            <span style={{ color: "#64748b" }}>{label}: </span>
            <span style={{ color: "#1e293b", fontWeight: 500 }}>{val ?? "—"}</span>
          </div>
        ))}
      </div>
      <ArtifactPreviewPane
        artifactId={data.artifact_id}
        mediaType={data.media_type}
        rowCount={data.row_count}
        summaryPreview={data.summary_preview}
      />
    </div>
  );
}
