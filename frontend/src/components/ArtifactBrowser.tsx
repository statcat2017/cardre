import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ArtifactListItem } from "../types";

interface Props {
  projectId: string;
}

const ROLES = ["", "input", "train", "test", "oot", "report", "definition", "model", "scorecard"];
const TYPES = ["", "dataset", "report", "definition", "model", "scorecard"];

function ArtifactRow({
  item,
  expanded,
  onToggle,
}: {
  item: ArtifactListItem;
  expanded: boolean;
  onToggle: () => void;
}) {
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

function ArtifactSummaryInline({ artifactId }: { artifactId: string }) {
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
    ["Rows", data.row_count],
    ["Columns", data.column_count],
  ];

  return (
    <div
      style={{
        marginLeft: 16,
        marginTop: 4,
        padding: "8px 12px",
        border: "1px solid #dbeafe",
        borderRadius: 4,
        backgroundColor: "#f8fafc",
        fontSize: 11,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, color: "#1e293b", fontSize: 12 }}>Summary</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
        {metaRows.map(([label, val]) => (
          <div key={label}>
            <span style={{ color: "#64748b" }}>{label}: </span>
            <span style={{ color: "#1e293b", fontWeight: 500 }}>{val ?? "—"}</span>
          </div>
        ))}
      </div>
      {data.summary_preview && (
        <div style={{ marginTop: 8 }}>
          <div style={{ color: "#64748b", marginBottom: 2 }}>Preview</div>
          <pre
            style={{
              margin: 0,
              padding: 8,
              backgroundColor: "#fff",
              border: "1px solid #e2e8f0",
              borderRadius: 4,
              fontSize: 10,
              maxHeight: 160,
              overflow: "auto",
              color: "#334155",
            }}
          >
            {JSON.stringify(data.summary_preview, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export function ArtifactBrowser({ projectId }: Props) {
  const [role, setRole] = useState("");
  const [artifactType, setArtifactType] = useState("");
  const [limit] = useState(100);
  const [offset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const params: Record<string, string | number> = { limit, offset };
  if (role) params.role = role;
  if (artifactType) params.artifact_type = artifactType;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["projectArtifacts", projectId, params],
    queryFn: () =>
      api.getProjectArtifacts(projectId, {
        role: role || undefined,
        artifact_type: artifactType || undefined,
        limit,
        offset,
      }),
    enabled: !!projectId,
  });

  const artifacts: ArtifactListItem[] = data?.artifacts ?? [];

  return (
    <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Artefacts</h3>

      <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
        <label style={{ fontSize: 11, color: "#64748b" }}>
          Role
          <select
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              setExpandedId(null);
            }}
            style={{
              display: "block",
              marginTop: 2,
              padding: "4px 8px",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              fontSize: 12,
              backgroundColor: "#fff",
            }}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r || "All"}
              </option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 11, color: "#64748b" }}>
          Type
          <select
            value={artifactType}
            onChange={(e) => {
              setArtifactType(e.target.value);
              setExpandedId(null);
            }}
            style={{
              display: "block",
              marginTop: 2,
              padding: "4px 8px",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              fontSize: 12,
              backgroundColor: "#fff",
            }}
          >
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t || "All"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading && <div style={{ color: "#64748b", fontSize: 13 }}>Loading artefacts...</div>}
      {isError && (
        <div style={{ color: "#dc2626", fontSize: 13 }}>
          Failed to load artefacts: {(error as Error)?.message || "Unknown error"}
        </div>
      )}

      {!isLoading && !isError && artifacts.length === 0 && (
        <div style={{ color: "#64748b", fontSize: 13 }}>
          No artefacts yet. Import a dataset and run the pathway to generate artefacts.
        </div>
      )}

      {artifacts.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 70px 80px 90px 130px",
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
            <span>Artifact ID</span>
            <span>Role</span>
            <span>Type</span>
            <span>Format</span>
            <span>Created</span>
          </div>
          {artifacts.map((item) => (
            <ArtifactRow
              key={item.artifact_id}
              item={item}
              expanded={expandedId === item.artifact_id}
              onToggle={() =>
                setExpandedId(expandedId === item.artifact_id ? null : item.artifact_id)
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
