import React from "react";

interface Props {
  profileJson: Record<string, unknown> | null;
  loading: boolean;
}

export function ProfileOutput({ profileJson, loading }: Props) {
  if (loading) {
    return <div style={{ color: "#6b7280" }}>Loading profile...</div>;
  }

  if (!profileJson) {
    return <div style={{ color: "#6b7280" }}>No profile data.</div>;
  }

  return (
    <div>
      <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Profile</h3>
      <pre
        style={{
          fontSize: 11,
          backgroundColor: "#f9fafb",
          padding: 8,
          borderRadius: 4,
          border: "1px solid #e5e7eb",
          overflow: "auto",
          maxHeight: 200,
        }}
      >
        {JSON.stringify(profileJson, null, 2)}
      </pre>
    </div>
  );
}
