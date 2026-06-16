import React from 'react';

interface Props {
  selectedVars: string[];
  sourceBins: Record<string, { bins?: Record<string, unknown>[] }>;
  draftOverrides: Record<string, unknown>[];
}

export function SourceBinsChips({ selectedVars, sourceBins, draftOverrides }: Props) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", marginBottom: 8 }}>
        Source Bins ({selectedVars.length} selected variable{selectedVars.length !== 1 ? "s" : ""})
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {selectedVars.map((v) => {
          const bins = sourceBins[v]?.bins || [];
          const hasOverride = draftOverrides.some((o) => o.variable === v);
          return (
            <div
              key={v}
              style={{
                padding: "4px 10px",
                borderRadius: 12,
                border: `1px solid ${hasOverride ? "#3b82f6" : "#e2e8f0"}`,
                backgroundColor: hasOverride ? "#eff6ff" : "#f8fafc",
                fontSize: 11,
                color: hasOverride ? "#2563eb" : "#475569",
                fontWeight: hasOverride ? 600 : 400,
              }}
            >
              {v} ({bins.length} bins{hasOverride ? " · edited" : ""})
            </div>
          );
        })}
      </div>
    </div>
  );
}
