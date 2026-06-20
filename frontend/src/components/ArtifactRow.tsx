import React from "react";
import type { ArtifactListItem } from "../types";
import { ArtifactSummaryInline } from "./ArtifactSummaryInline";
import { theme } from "../styles";

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
          border: `1px solid ${expanded ? theme.text : theme.border}`,
          borderRadius: 4,
          backgroundColor: expanded ? theme.surface : theme.surface,
          fontSize: 12,
          alignItems: "center",
          cursor: "pointer",
        }}
      >
        <span style={{ fontFamily: theme.fontMono, fontSize: 11, color: theme.textSoft }}>
          {item.artifact_id.slice(0, 12)}…
        </span>
        <span style={{ color: theme.muted }}>{item.role}</span>
        <span style={{ color: theme.muted }}>{item.artifact_type}</span>
        <span style={{ color: theme.muted, fontSize: 11 }}>{item.media_type.split("/").pop()}</span>
        <span style={{ fontSize: 11, color: theme.mutedSoft }}>
          {item.created_at ? new Date(item.created_at).toLocaleString() : "—"}
        </span>
      </div>
      {expanded && <ArtifactSummaryInline artifactId={item.artifact_id} />}
    </div>
  );
}
