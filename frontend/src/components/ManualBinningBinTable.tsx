import React from "react";
import type { ManualBinningVariableSummary } from "../types";
import { theme, tableHeaderStyle, tableDataStyle } from "../styles";

interface BinData {
  bin_id?: string;
  label?: string;
  min?: number | null;
  max?: number | null;
  count?: number;
  good_count?: number;
  bad_count?: number;
  bad_rate?: number;
  woe?: number;
  iv_contrib?: number;
  is_missing?: boolean;
  is_special?: boolean;
}

interface Props {
  variable: string | null;
  sourceBins: Record<string, unknown> | null;
  summary: ManualBinningVariableSummary | null | undefined;
  onEdit?: (variable: string) => void;
}

export function ManualBinningBinTable({ variable, sourceBins, summary: _summary, onEdit }: Props) {
  if (!variable || !sourceBins) {
    return (
      <div style={{ padding: 16, fontSize: 11, color: theme.muted, textAlign: "center" }}>
        Select a variable to view bin details.
      </div>
    );
  }

  const bins = (sourceBins.bins as BinData[] | undefined) ?? [];
  if (bins.length === 0) {
    return (
      <div style={{ padding: 16, fontSize: 11, color: theme.muted }}>
        No bin data available for <strong>{variable}</strong>.
      </div>
    );
  }

  return (
    <div
      style={{
        marginTop: 16,
        border: `1px solid ${theme.border}`,
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          backgroundColor: theme.surfaceMuted,
          borderBottom: `1px solid ${theme.border}`,
          fontSize: 11,
          fontWeight: 600,
          color: theme.text,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span>Bin Details — {variable}</span>
        {onEdit && (
          <button
            onClick={() => onEdit(variable)}
            style={{
              marginLeft: "auto",
              padding: "2px 8px",
              borderRadius: 3,
              border: `1px solid ${theme.border}`,
              backgroundColor: theme.surface,
              fontSize: 10,
              fontWeight: 500,
              color: theme.textSoft,
              cursor: "pointer",
            }}
          >
            Edit bins
          </button>
        )}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
          <thead>
            <tr style={{ backgroundColor: theme.canvasSoft }}>
              <th style={tableHeaderStyle}>Bin</th>
              <th style={tableHeaderStyle}>Range</th>
              <th style={tableHeaderStyle}>Count</th>
              <th style={tableHeaderStyle}>Good</th>
              <th style={tableHeaderStyle}>Bad</th>
              <th style={tableHeaderStyle}>Bad Rate</th>
              <th style={tableHeaderStyle}>WOE</th>
              <th style={tableHeaderStyle}>IV</th>
              <th style={tableHeaderStyle}>Flags</th>
            </tr>
          </thead>
          <tbody>
            {bins.map((b: BinData, i: number) => {
              const range =
                b.min != null || b.max != null
                  ? `${b.min ?? "—"} – ${b.max ?? "—"}`
                  : b.label || b.bin_id || "—";
              const woe = b.woe != null ? b.woe.toFixed(4) : "—";
              const ivContrib = b.iv_contrib != null ? b.iv_contrib.toFixed(4) : "—";
              const count = b.count ?? "—";
              const good = b.good_count ?? "—";
              const bad = b.bad_count ?? "—";
              const badRate = b.bad_rate != null ? b.bad_rate.toFixed(3) : "—";

              const flags: string[] = [];
              if (b.is_missing) flags.push("Missing");
              if (b.is_special) flags.push("Special");
              if (b.bad_count === 0) flags.push("Zero bad");
              if (b.good_count === 0) flags.push("Zero good");
              const warnColor = flags.length > 0 ? theme.yellowText : theme.textSoft;

              return (
                <tr key={b.bin_id || i} style={{ borderBottom: `1px solid ${theme.border}` }}>
                  <td style={tableDataStyle}>{b.label || b.bin_id || i}</td>
                  <td style={tableDataStyle}>{range}</td>
                  <td style={tableDataStyle}>{count}</td>
                  <td style={tableDataStyle}>{good}</td>
                  <td style={tableDataStyle}>{bad}</td>
                  <td style={tableDataStyle}>{badRate}</td>
                  <td style={tableDataStyle}>{woe}</td>
                  <td style={tableDataStyle}>{ivContrib}</td>
                  <td style={{ ...tableDataStyle, color: warnColor }}>
                    {flags.length > 0 ? flags.join(", ") : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
