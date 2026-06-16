import React from "react";
import type { ArtifactListItem } from "../types";
import { ArtifactSummaryInline } from "./ArtifactSummaryInline";

interface Props {
  item: ArtifactListItem;
  expanded: boolean;
  onToggle: () => void;
}

export function ArtifactRow({ item, expanded, onToggle }: Props) {
  return (
    <div>
      <div
        onClick={onToggle}
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 70px 80px 90px 130px",
          gap: 8,
          padding: "8px",
          border: `1px solid ${expanded ? "#3b82f6" : "#e2e8f0"}`,
          borderRadius: 4,
          backgroundColor: expanded ? "#eff6ff" : "#fff",
          fontSize: 12,
          alignItems: "center",
          cursor: "pointer",
        }}
      >
        <span style={{ fontFamily: "monospace", fontSize: 11, color: "#475569" }}>
          {item.artifact_id.slice(0, 12)}…
        </span>
        <span style={{ color: "#64748b" }}>{item.role}</span>
        <span style={{ color: "#64748b" }}>{item.artifact_type}</span>
        <span style={{ color: "#64748b", fontSize: 11 }}>{item.media_type.split("/").pop()}</span>
        <span style={{ fontSize: 11, color: "#94a3b8" }}>
          {item.created_at ? new Date(item.created_at).toLocaleString() : "—"}
        </span>
      </div>
      {expanded && <ArtifactSummaryInline artifactId={item.artifact_id} />}
    </div>
  );
}
