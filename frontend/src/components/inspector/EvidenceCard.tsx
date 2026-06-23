import React from "react";
import type { RunStepEvidenceItem } from "../../types";
import { theme } from "../../styles";
import { evidenceKindLabel, evidenceStatusLabel } from "../../utils/evidenceLabels";

interface EvidenceCardProps {
  item: RunStepEvidenceItem;
}

const statusColors: Record<string, { bg: string; text: string }> = {
  current: { bg: theme.greenBg, text: theme.greenText },
  stale: { bg: theme.yellowBg, text: theme.yellowText },
  partial: { bg: theme.yellowBg, text: theme.yellowText },
  missing: { bg: theme.redBg, text: theme.redText },
  unsupported: { bg: "#F0F0F0", text: theme.muted },
};

function formatSummary(item: RunStepEvidenceItem): string {
  const s = item.summary as Record<string, any> | undefined;
  if (!s || Object.keys(s).length === 0) return "";
  const parts: string[] = [];
  const kind = item.evidence_kind || "";

  if (kind === "profile" || kind === "import") {
    if (s.row_count !== undefined) parts.push(`${s.row_count} rows`);
    if (s.column_count !== undefined) parts.push(`${s.column_count} cols`);
    if (s.dataset_role) parts.push(`role: ${s.dataset_role}`);
  } else if (kind === "target-definition") {
    if (s.target_column) parts.push(`target: ${s.target_column}`);
    if (s.event_rate !== undefined) parts.push(`event rate: ${(s.event_rate * 100).toFixed(1)}%`);
  } else if (kind === "split") {
    if (s.train_count !== undefined) parts.push(`train: ${s.train_count}`);
    if (s.test_count !== undefined) parts.push(`test: ${s.test_count}`);
    if (s.oot_count !== undefined) parts.push(`oot: ${s.oot_count}`);
  } else if (kind === "binning") {
    if (s.variable_count !== undefined) parts.push(`${s.variable_count} variables`);
    if (s.bin_total !== undefined) parts.push(`${s.bin_total} bins`);
  } else if (kind === "woe-iv") {
    if (s.selected_variable_count !== undefined) parts.push(`${s.selected_variable_count} variables`);
    if (s.iv_min !== undefined && s.iv_max !== undefined) {
      parts.push(`IV range ${s.iv_min.toFixed(2)} – ${s.iv_max.toFixed(2)}`);
    }
    if (s.top_variables?.length) {
      const top3 = s.top_variables.slice(0, 3).map((v: any) => `${v.name} ${v.iv.toFixed(2)}`);
      return `Top IV: ${top3.join(", ")}`;
    }
  } else if (kind === "logistic-model") {
    if (s.variable_count !== undefined) parts.push(`${s.variable_count} variables`);
    if (s.coefficient_count !== undefined) parts.push(`${s.coefficient_count} coefficients`);
    if (s.fit_status) parts.push(`fit: ${s.fit_status}`);
  } else if (kind === "score-scaling") {
    if (s.score_min !== undefined && s.score_max !== undefined) {
      parts.push(`score range ${s.score_min} – ${s.score_max}`);
    }
    if (s.pdo !== undefined) parts.push(`PDO ${s.pdo}`);
  } else if (kind === "validation-metrics") {
    if (s.gini !== undefined) parts.push(`Gini ${s.gini.toFixed(3)}`);
    if (s.ks !== undefined) parts.push(`KS ${s.ks.toFixed(3)}`);
    if (s.auc !== undefined) parts.push(`AUC ${s.auc.toFixed(3)}`);
  } else if (kind === "report-bundle") {
    if (s.ready !== undefined) parts.push(s.ready ? "Ready" : "Blocked");
    if (s.blocker_count !== undefined) parts.push(`${s.blocker_count} blockers`);
    if (s.warning_count !== undefined) parts.push(`${s.warning_count} warnings`);
  }

  if (parts.length === 0 && s.unsupported_kind) {
    return "This artifact kind has no summary yet.";
  }

  return parts.join(" · ");
}

export function EvidenceCard({ item }: EvidenceCardProps) {
  const label = evidenceKindLabel(item.evidence_kind);
  const statusLabel = evidenceStatusLabel(item.status);
  const colors = statusColors[item.status] || statusColors.unsupported;

  const warnings = item.warnings ?? [];

  return (
    <div
      style={{
        padding: 12,
        border: `1px solid ${theme.border}`,
        borderRadius: 8,
        backgroundColor: theme.surfaceMuted,
        fontSize: 12,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {/* Title row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontWeight: 600, color: theme.text }}>{label}</span>
        <span
          style={{
            padding: "2px 8px",
            borderRadius: 4,
            fontSize: 10,
            fontWeight: 500,
            backgroundColor: colors.bg,
            color: colors.text,
          }}
        >
          {statusLabel}
        </span>
      </div>

      {/* Summary line */}
      {item.status !== "unsupported" && (
        <div style={{ color: theme.textSoft, fontSize: 11, lineHeight: 1.4 }}>
          {formatSummary(item)}
        </div>
      )}
      {item.status === "unsupported" && (
        <div style={{ color: theme.muted, fontSize: 11, fontStyle: "italic" }}>
          This artifact kind has no summary yet.
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {warnings.slice(0, 3).map((w: string, i: number) => (
            <div key={i} style={{ color: theme.yellowText, fontSize: 10 }}>
              ⚠ {w}
            </div>
          ))}
          {warnings.length > 3 && (
            <div style={{ color: theme.muted, fontSize: 10 }}>
              +{warnings.length - 3} more
            </div>
          )}
        </div>
      )}

      {/* Audit metadata */}
      <div
        style={{
          color: theme.mutedSoft,
          fontSize: 9,
          fontFamily: theme.fontMono,
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span>id: {item.artifact_id.slice(0, 12)}…</span>
        <span>hash: {(item.logical_hash || "").slice(0, 12)}…</span>
        {item.created_at && <span>created: {item.created_at.slice(0, 10)}</span>}
        {item.media_type && <span>{item.media_type}</span>}
      </div>
    </div>
  );
}
