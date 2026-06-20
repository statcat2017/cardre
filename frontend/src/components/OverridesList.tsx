import React from 'react';
import { theme } from '../styles';

interface Props {
  overrides: Record<string, unknown>[];
  onRemoveOverride: (index: number) => void;
}

export function OverridesList({ overrides, onRemoveOverride }: Props) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: theme.text, marginBottom: 8 }}>
        Overrides ({overrides.length})
      </div>
      {overrides.length === 0 && (
        <div style={{ color: theme.mutedSoft, fontSize: 12 }}>No overrides yet. Add one below.</div>
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
              border: `1px solid ${theme.border}`,
              borderRadius: 4,
              backgroundColor: theme.surfaceMuted,
              fontSize: 11,
            }}
          >
            <span style={{ fontWeight: 600, color: theme.blueText, minWidth: 80 }}>
              {String(o.action)}
            </span>
            <span style={{ color: theme.text, minWidth: 100 }}>{String(o.variable)}</span>
            <span style={{ color: theme.muted, minWidth: 120 }}>
              bins: {(o.source_bin_ids as string[])?.join(", ") || "—"}
            </span>
            <span style={{ color: theme.mutedSoft, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {String(o.reason || "—")}
            </span>
            <button
              onClick={() => onRemoveOverride(i)}
              style={{
                border: "none",
                background: "none",
                color: theme.redText,
                cursor: "pointer",
                fontSize: 11,
                padding: 0,
              }}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
