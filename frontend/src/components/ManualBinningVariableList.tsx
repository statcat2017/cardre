import React, { useState, useMemo } from "react";
import type { ManualBinningVariableSummary } from "../types";
import { theme } from "../styles";

interface Props {
  summaries: ManualBinningVariableSummary[];
  stepStatus: string;
  selected: string | null;
  onSelect: (variable: string) => void;
}

type SortKey = "variable" | "iv" | "bin_count" | "missing_rate" | "special_rate" | "warning_count";
type SortDir = "asc" | "desc";

function warningCount(vs: ManualBinningVariableSummary): number {
  return (vs.zero_cell_warning_count || 0) + (vs.sparse_bin_warning_count || 0);
}

function reviewBadgeLabel(vs: ManualBinningVariableSummary, stepStatus: string): string | null {
  if (stepStatus === "accepted_automated") return "Accepted";
  if (stepStatus === "reviewed") return "Reviewed";
  if (vs.edited) return "Edited";
  if (vs.review_required) return "Needs review";
  return null;
}

function reviewBadgeStyle(label: string): React.CSSProperties {
  const base: React.CSSProperties = {
    display: "inline-block",
    padding: "0 6px",
    borderRadius: 3,
    fontSize: 9,
    fontWeight: 600,
    lineHeight: "18px",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  };
  if (label === "Needs review")
    return { ...base, backgroundColor: theme.yellowBg, color: theme.yellowText };
  if (label === "Edited") return { ...base, backgroundColor: theme.blueBg, color: theme.blueText };
  if (label === "Accepted")
    return { ...base, backgroundColor: theme.greenBg, color: theme.greenText };
  if (label === "Reviewed")
    return { ...base, backgroundColor: theme.greenBg, color: theme.greenText };
  return { ...base, backgroundColor: theme.surfaceMuted, color: theme.muted };
}

function monoBadge(status: string): { label: string; style: React.CSSProperties } {
  if (status === "monotonic") return { label: "Mono", style: { color: theme.greenText } };
  if (status === "non_monotonic") return { label: "Non-mono", style: { color: theme.yellowText } };
  return { label: "—", style: { color: theme.mutedSoft } };
}

const cellStyle: React.CSSProperties = {
  padding: "6px 8px",
  fontSize: 11,
  borderBottom: `1px solid ${theme.border}`,
  color: theme.textSoft,
  cursor: "pointer",
};

const headerCellStyle: React.CSSProperties = {
  padding: "6px 8px",
  fontSize: 10,
  fontWeight: 600,
  color: theme.muted,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  borderBottom: `1px solid ${theme.border}`,
  textAlign: "left",
  cursor: "pointer",
  userSelect: "none",
};

export function ManualBinningVariableList({ summaries, stepStatus, selected, onSelect }: Props) {
  const [search, setSearch] = useState("");
  const [filterTag, setFilterTag] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("variable");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const filtered = useMemo(() => {
    let items = [...summaries];
    if (search) {
      const q = search.toLowerCase();
      items = items.filter((v) => v.variable.toLowerCase().includes(q));
    }
    if (filterTag === "needs_review") items = items.filter((v) => v.review_required);
    else if (filterTag === "edited") items = items.filter((v) => v.edited);
    else if (filterTag === "warnings") items = items.filter((v) => warningCount(v) > 0);

    items.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "variable":
          cmp = a.variable.localeCompare(b.variable);
          break;
        case "iv":
          cmp = (a.iv ?? -1) - (b.iv ?? -1);
          break;
        case "bin_count":
          cmp = (a.bin_count ?? 0) - (b.bin_count ?? 0);
          break;
        case "missing_rate":
          cmp = (a.missing_rate ?? 0) - (b.missing_rate ?? 0);
          break;
        case "special_rate":
          cmp = (a.special_rate ?? 0) - (b.special_rate ?? 0);
          break;
        case "warning_count":
          cmp = warningCount(a) - warningCount(b);
          break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return items;
  }, [summaries, search, filterTag, sortKey, sortDir]);

  const needsReviewCount = summaries.filter((v) => v.review_required).length;
  const editedCount = summaries.filter((v) => v.edited).length;
  const warnTotal = summaries.reduce((s, v) => s + warningCount(v), 0);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const sortArrow = (key: SortKey) => {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  };

  const filterChipStyle = (active: boolean): React.CSSProperties => ({
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 12,
    border: `1px solid ${active ? theme.text : theme.border}`,
    backgroundColor: active ? theme.text : "transparent",
    color: active ? "#fff" : theme.muted,
    fontSize: 10,
    fontWeight: 500,
    cursor: "pointer",
    marginRight: 4,
  });

  return (
    <div style={{ width: "40%", minWidth: 280, overflow: "auto" }}>
      <div
        style={{
          padding: "8px 12px",
          borderBottom: `1px solid ${theme.border}`,
          display: "flex",
          alignItems: "center",
          gap: 6,
          flexWrap: "wrap",
        }}
      >
        <input
          type="text"
          placeholder="Search variables…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            flex: 1,
            minWidth: 100,
            padding: "4px 8px",
            border: `1px solid ${theme.border}`,
            borderRadius: 4,
            fontSize: 11,
            color: theme.text,
            backgroundColor: theme.surface,
            outline: "none",
          }}
        />
      </div>
      <div
        style={{
          padding: "4px 12px",
          fontSize: 10,
          color: theme.muted,
          borderBottom: `1px solid ${theme.border}`,
        }}
      >
        {summaries.length} variables · {needsReviewCount} need review · {editedCount} edited ·{" "}
        {warnTotal} warnings
        {filterTag && (
          <span style={{ marginLeft: 8 }}>
            <button onClick={() => setFilterTag(null)} style={{ ...filterChipStyle(true) }}>
              Clear filter
            </button>
          </span>
        )}
      </div>
      <div
        style={{
          padding: "4px 12px",
          display: "flex",
          gap: 4,
          borderBottom: `1px solid ${theme.border}`,
          flexWrap: "wrap",
        }}
      >
        <span
          onClick={() => setFilterTag(filterTag === "needs_review" ? null : "needs_review")}
          style={filterChipStyle(filterTag === "needs_review")}
        >
          Needs review
        </span>
        <span
          onClick={() => setFilterTag(filterTag === "edited" ? null : "edited")}
          style={filterChipStyle(filterTag === "edited")}
        >
          Edited
        </span>
        <span
          onClick={() => setFilterTag(filterTag === "warnings" ? null : "warnings")}
          style={filterChipStyle(filterTag === "warnings")}
        >
          Warnings only
        </span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
        <thead>
          <tr>
            <th style={{ ...headerCellStyle, width: "30%" }} onClick={() => toggleSort("variable")}>
              Variable{sortArrow("variable")}
            </th>
            <th style={{ ...headerCellStyle, width: "12%" }} onClick={() => toggleSort("iv")}>
              IV{sortArrow("iv")}
            </th>
            <th style={{ ...headerCellStyle, width: "8%" }} onClick={() => toggleSort("bin_count")}>
              Bins{sortArrow("bin_count")}
            </th>
            <th
              style={{ ...headerCellStyle, width: "10%" }}
              onClick={() => toggleSort("missing_rate")}
            >
              Miss%{sortArrow("missing_rate")}
            </th>
            <th
              style={{ ...headerCellStyle, width: "10%" }}
              onClick={() => toggleSort("special_rate")}
            >
              Spec%{sortArrow("special_rate")}
            </th>
            <th style={{ ...headerCellStyle, width: "10%" }}>Mono</th>
            <th
              style={{ ...headerCellStyle, width: "10%" }}
              onClick={() => toggleSort("warning_count")}
            >
              Warn{sortArrow("warning_count")}
            </th>
            <th style={{ ...headerCellStyle, width: "10%" }}>Status</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((vs) => {
            const isSelected = vs.variable === selected;
            const badge = reviewBadgeLabel(vs, stepStatus);
            const mono = monoBadge(vs.monotonicity_status);
            return (
              <tr
                key={vs.variable}
                onClick={() => onSelect(vs.variable)}
                style={{
                  backgroundColor: isSelected ? theme.surfaceMuted : "transparent",
                  cursor: "pointer",
                }}
                onMouseEnter={(e) => {
                  if (!isSelected)
                    (e.currentTarget as HTMLElement).style.backgroundColor = theme.canvasSoft;
                }}
                onMouseLeave={(e) => {
                  if (!isSelected)
                    (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                }}
              >
                <td style={{ ...cellStyle, fontWeight: 500, color: theme.text }}>{vs.variable}</td>
                <td style={cellStyle}>{vs.iv != null ? vs.iv.toFixed(4) : "—"}</td>
                <td style={cellStyle}>{vs.bin_count ?? "—"}</td>
                <td style={cellStyle}>
                  {vs.missing_rate != null ? `${(vs.missing_rate * 100).toFixed(1)}%` : "—"}
                </td>
                <td style={cellStyle}>
                  {vs.special_rate != null ? `${(vs.special_rate * 100).toFixed(1)}%` : "—"}
                </td>
                <td style={{ ...cellStyle, color: mono.style.color }}>{mono.label}</td>
                <td style={cellStyle}>{warningCount(vs) > 0 ? warningCount(vs) : "—"}</td>
                <td style={cellStyle}>
                  {badge ? <span style={reviewBadgeStyle(badge)}>{badge}</span> : null}
                </td>
              </tr>
            );
          })}
          {filtered.length === 0 && (
            <tr>
              <td
                colSpan={8}
                style={{ ...cellStyle, textAlign: "center", color: theme.muted, padding: 24 }}
              >
                No variables match the current filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
