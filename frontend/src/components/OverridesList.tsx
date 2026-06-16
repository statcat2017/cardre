import React from 'react';

interface Props {
  overrides: Record<string, unknown>[];
  onRemoveOverride: (index: number) => void;
}

export function OverridesList({ overrides, onRemoveOverride }: Props) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", marginBottom: 8 }}>
        Overrides ({overrides.length})
      </div>
      {overrides.length === 0 && (
        <div style={{ color: "#94a3b8", fontSize: 12 }}>No overrides yet. Add one below.</div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {overrides.map((o, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 10px",
              border: "1px solid #e2e8f0",
              borderRadius: 4,
              backgroundColor: "#f8fafc",
              fontSize: 11,
            }}
          >
            <span style={{ fontWeight: 600, color: "#2563eb", minWidth: 80 }}>
              {String(o.action)}
            </span>
            <span style={{ color: "#1e293b", minWidth: 100 }}>{String(o.variable)}</span>
            <span style={{ color: "#64748b", minWidth: 120 }}>
              bins: {(o.source_bin_ids as string[])?.join(", ") || "—"}
            </span>
            <span style={{ color: "#94a3b8", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {String(o.reason || "—")}
            </span>
            <button
              onClick={() => onRemoveOverride(i)}
              style={{
                border: "none",
                background: "none",
                color: "#ef4444",
                cursor: "pointer",
                fontSize: 14,
                padding: 0,
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
