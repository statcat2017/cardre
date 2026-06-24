import React, { useMemo } from "react";
import type { ManualBinningEditorStateResponse, ManualBinningVariableSummary } from "../types";
import { theme } from "../styles";

interface Props {
  variable: string | null;
  state: ManualBinningEditorStateResponse;
}

function recommendedAction(vs: ManualBinningVariableSummary): string {
  if (vs.monotonicity_status === "non_monotonic") return "Review monotonicity; merge adjacent bins or accept with a `monotonicity` reason code.";
  if ((vs.zero_cell_warning_count || 0) > 0) return "Address zero-cell bin: merge, isolate, or accept with a `zero_cell` reason code.";
  if ((vs.sparse_bin_warning_count || 0) > 0) return "Merge sparse bin with a neighbour, or accept with a `sparse_bin` reason code.";
  if ((vs.missing_count || 0) > 0) return "Confirm missing handling with the `missing_value_treatment` reason code.";
  if ((vs.special_bin_count || 0) > 0) return "Confirm special handling with the `special_value_treatment` reason code.";
  return "No action required; optionally accept automated bins.";
}

function warningsForVariable(vs: ManualBinningVariableSummary): { code: string; message: string }[] {
  const w: { code: string; message: string }[] = [];
  if (vs.monotonicity_status === "non_monotonic") w.push({ code: "NON_MONOTONIC", message: `WOE is not monotonic across bins (${vs.iv} IV).` });
  if ((vs.zero_cell_warning_count || 0) > 0) w.push({ code: "ZERO_CELL", message: `${vs.zero_cell_warning_count} bin(s) have zero good or bad count.` });
  if ((vs.sparse_bin_warning_count || 0) > 0) w.push({ code: "SPARSE_BIN", message: `${vs.sparse_bin_warning_count} bin(s) are below 5% of total observations.` });
  if ((vs.missing_count || 0) > 0) w.push({ code: "MISSING_BINS", message: `${vs.missing_count} missing bin(s) present.` });
  if ((vs.special_bin_count || 0) > 0) w.push({ code: "SPECIAL_BINS", message: `${vs.special_bin_count} special value bin(s) present.` });
  return w;
}

export function ManualBinningReviewPanel({ variable, state }: Props) {
  const vs = useMemo(
    () => state.variable_summaries?.find((s) => s.variable === variable) ?? null,
    [variable, state.variable_summaries],
  );

  const sourceBins = variable ? (state.source_bins_by_variable as Record<string, any>)?.[variable] : null;

  if (!variable) {
    return (
      <div style={{ padding: 16, fontSize: 11, color: theme.muted, textAlign: "center" }}>
        Select a variable to review.
      </div>
    );
  }

  if (!vs) {
    return (
      <div style={{ padding: 16, fontSize: 11, color: theme.muted }}>
        No summary data available for <strong>{variable}</strong>.
      </div>
    );
  }

  const warnings = warningsForVariable(vs);
  const action = recommendedAction(vs);

  // Evidence summary
  const binsList = sourceBins?.bins ?? [];
  const badRates = binsList.map((b: any) => b.bad_rate).filter((r: number) => r != null);
  const woes = binsList.map((b: any) => b.woe).filter((w: number) => w != null);
  const minBadRate = badRates.length ? Math.min(...badRates).toFixed(3) : "—";
  const maxBadRate = badRates.length ? Math.max(...badRates).toFixed(3) : "—";
  const minWoe = woes.length ? Math.min(...woes).toFixed(3) : "—";
  const maxWoe = woes.length ? Math.max(...woes).toFixed(3) : "—";

  const blockStyle: React.CSSProperties = {
    padding: 12,
    borderBottom: `1px solid ${theme.border}`,
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 9,
    fontWeight: 600,
    color: theme.muted,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    marginBottom: 4,
  };

  return (
    <div style={{ border: `1px solid ${theme.border}`, borderRadius: 8, overflow: "hidden" }}>
      <div style={{ padding: 12, backgroundColor: theme.surfaceMuted, borderBottom: `1px solid ${theme.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <strong style={{ fontSize: 13, color: theme.text }}>{variable}</strong>
          <span style={{ fontSize: 10, color: theme.muted }}>{vs.variable_type || "—"}</span>
        </div>
      </div>

      <div style={blockStyle}>
        <div style={labelStyle}>Overview</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px", fontSize: 11 }}>
          <span style={{ color: theme.muted }}>IV</span><span style={{ color: theme.text }}>{vs.iv != null ? vs.iv.toFixed(4) : "—"}</span>
          <span style={{ color: theme.muted }}>Bins</span><span style={{ color: theme.text }}>{vs.bin_count ?? "—"}</span>
          <span style={{ color: theme.muted }}>Missing rate</span><span style={{ color: theme.text }}>{vs.missing_rate != null ? `${(vs.missing_rate * 100).toFixed(1)}%` : "—"}</span>
          <span style={{ color: theme.muted }}>Special rate</span><span style={{ color: theme.text }}>{vs.special_rate != null ? `${(vs.special_rate * 100).toFixed(1)}%` : "—"}</span>
          <span style={{ color: theme.muted }}>Monotonicity</span><span style={{ color: theme.text }}>{vs.monotonicity_status}</span>
        </div>
      </div>

      <div style={blockStyle}>
        <div style={labelStyle}>Evidence Summary</div>
        <div style={{ fontSize: 11, color: theme.textSoft }}>
          {binsList.length} bins · bad rate {minBadRate}–{maxBadRate} · WOE {minWoe}–{maxWoe} · IV {vs.iv != null ? vs.iv.toFixed(4) : "—"}
        </div>
      </div>

      {warnings.length > 0 && (
        <div style={blockStyle}>
          <div style={labelStyle}>Current Warnings</div>
          {warnings.map((w, i) => (
            <div key={i} style={{ fontSize: 11, color: theme.yellowText, padding: "2px 0" }}>
              <strong>{w.code}</strong>: {w.message}
            </div>
          ))}
        </div>
      )}

      <div style={{ ...blockStyle, borderBottom: "none" }}>
        <div style={labelStyle}>Recommended Action</div>
        <div style={{ fontSize: 11, color: theme.textSoft, lineHeight: "1.4" }}>{action}</div>
      </div>
    </div>
  );
}
