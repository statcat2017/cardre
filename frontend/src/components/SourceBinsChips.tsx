import React from 'react';
import { theme } from '../styles';

interface Props {
  selectedVars: string[];
  sourceBins: Record<string, { bins?: Record<string, unknown>[] }>;
  draftOverrides: Record<string, unknown>[];
}

export function SourceBinsChips({ selectedVars, sourceBins, draftOverrides }: Props) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: theme.text, marginBottom: 8 }}>
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
                borderRadius: 9999,
                border: `1px solid ${theme.border}`,
                backgroundColor: hasOverride ? theme.blueBg : theme.canvasSoft,
                fontSize: 11,
                color: hasOverride ? theme.blueText : theme.textSoft,
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
