import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ArtifactListItem } from "../types";
import { ArtifactRow } from "./ArtifactRow";

interface Props {
  projectId: string;
}

const ROLES = ["", "input", "train", "test", "oot", "report", "definition", "model", "scorecard"];
const TYPES = ["", "dataset", "report", "definition", "model", "scorecard"];

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
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Artifacts</h3>

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

      {isLoading && <div style={{ color: "#64748b", fontSize: 13 }}>Loading artifacts...</div>}
      {isError && (
        <div style={{ color: "#dc2626", fontSize: 13 }}>
          Failed to load artifacts: {(error as Error)?.message || "Unknown error"}
        </div>
      )}

      {!isLoading && !isError && artifacts.length === 0 && (
        <div style={{ color: "#64748b", fontSize: 13 }}>
          No artifacts yet. Import a dataset and run the pathway to generate artifacts.
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
