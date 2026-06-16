import React from 'react';
import { tableHeaderStyle, tableDataStyle } from '../styles';

interface Props {
  selectedVars: string[];
  sourceBins: Record<string, { bins?: Record<string, unknown>[] }>;
  loading: boolean;
}

export function BinDetailsAccordion({ selectedVars, sourceBins }: Props) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", marginBottom: 8 }}>
        Bin Details
      </div>
      {selectedVars.slice(0, 5).map((v) => {
        const bins = sourceBins[v]?.bins || [];
        return (
          <details key={v} style={{ marginBottom: 6 }}>
            <summary style={{ cursor: "pointer", fontSize: 12, color: "#334155", fontWeight: 500 }}>
              {v} ({bins.length} bins)
            </summary>
            <div
              style={{
                marginTop: 4,
                marginLeft: 12,
                padding: "4px 8px",
                border: "1px solid #e2e8f0",
                borderRadius: 4,
                backgroundColor: "#fff",
                maxHeight: 200,
                overflowY: "auto",
                fontSize: 10,
              }}
            >
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
                    <th style={tableHeaderStyle}>Bin ID</th>
                    <th style={tableHeaderStyle}>Lower</th>
                    <th style={tableHeaderStyle}>Upper</th>
                    <th style={tableHeaderStyle}>Rows</th>
                    <th style={tableHeaderStyle}>Good</th>
                    <th style={tableHeaderStyle}>Bad</th>
                  </tr>
                </thead>
                <tbody>
                  {bins.map((b: Record<string, unknown>, i: number) => (
                    <tr key={String(b.bin_id || i)}>
                      <td style={tableDataStyle}>{String(b.bin_id || "—").slice(0, 16)}</td>
                      <td style={tableDataStyle}>{b.lower !== undefined ? String(b.lower) : "—"}</td>
                      <td style={tableDataStyle}>{b.upper !== undefined ? String(b.upper) : "—"}</td>
                      <td style={tableDataStyle}>{String(b.row_count ?? "—")}</td>
                      <td style={tableDataStyle}>{String(b.good_count ?? "—")}</td>
                      <td style={tableDataStyle}>{String(b.bad_count ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        );
      })}
      {selectedVars.length > 5 && (
        <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>
          +{selectedVars.length - 5} more variables
        </div>
      )}
    </div>
  );
}
