import React from "react";

interface Artifact {
  artifact_id: string;
  artifact_type: string;
  role: string;
  path: string;
  physical_hash: string;
  logical_hash: string;
}

interface Props {
  artifacts: Artifact[];
  loading: boolean;
}

export function ArtifactList({ artifacts, loading }: Props) {
  if (loading) {
    return <div style={{ color: "#6b7280" }}>Loading artifacts...</div>;
  }

  if (artifacts.length === 0) {
    return <div style={{ color: "#6b7280" }}>No artifacts yet.</div>;
  }

  return (
    <div>
      <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Artifacts</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {artifacts.map((a) => (
          <div
            key={a.artifact_id}
            style={{
              padding: "6px 8px",
              borderRadius: 4,
              backgroundColor: "#f9fafb",
              fontSize: 12,
              border: "1px solid #e5e7eb",
            }}
          >
            <div>
              <strong>{a.role}</strong> · {a.artifact_type}
            </div>
            <div style={{ color: "#6b7280", fontSize: 11, fontFamily: "monospace" }}>
              {a.logical_hash.slice(0, 12)}…
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
