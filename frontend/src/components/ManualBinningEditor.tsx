import React, { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ManualBinningEditorStateResponse, ManualBinningPreviewResponse } from "../types";

interface Props {
  planId: string;
  projectId: string;
  basePlanVersionId: string;
  onBack: () => void;
  onPlanRefreshed: (detail: { latest_version_id?: string }) => void;
}

export function ManualBinningEditor({
  planId,
  projectId,
  basePlanVersionId,
  onBack,
  onPlanRefreshed,
}: Props) {
  const queryClient = useQueryClient();

  const editorStateQuery = useQuery({
    queryKey: ["manualBinningEditorState", planId, projectId],
    queryFn: () => api.getManualBinningEditorState(planId, projectId),
    enabled: !!planId && !!projectId,
  });

  const [overrideVar, setOverrideVar] = useState("");
  const [overrideAction, setOverrideAction] = useState("merge_bins");
  const [overrideBinIds, setOverrideBinIds] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideLabel, setOverrideLabel] = useState("");
  const [draftOverrides, setDraftOverrides] = useState<Record<string, unknown>[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgType, setMsgType] = useState<"error" | "info" | "success">("info");

  // Preview mutations
  const previewMutation = useMutation({
    mutationFn: (overrides: Record<string, unknown>[]) =>
      api.previewManualBinning(planId, {
        project_id: projectId,
        plan_version_id: basePlanVersionId,
        overrides,
      }),
  });

  const saveMutation = useMutation({
    mutationFn: (overrides: Record<string, unknown>[]) =>
      api.updateStepParams(planId, "manual-binning", {
        project_id: projectId,
        base_plan_version_id: basePlanVersionId,
        params: { overrides },
      }),
    onSuccess: () => {
      setMsg("Manual binning overrides saved.");
      setMsgType("success");
      loadedRef.current = false;
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState", planId, projectId] });
    },
    onError: (err: any) => {
      if (err?.status === 409 && err?.detail?.code === "STALE_VERSION") {
        setMsg("Plan was modified externally. Refreshing editor state…");
        setMsgType("info");
        loadedRef.current = false;
        queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState", planId, projectId] });
        onPlanRefreshed(err.detail);
      } else if (err?.status === 422) {
        setMsg(err?.detail?.message || "Validation failed");
        setMsgType("error");
      } else {
        setMsg(err?.message || "Save failed");
        setMsgType("error");
      }
    },
  });

  const addOverride = () => {
    if (!overrideVar || !overrideReason) {
      setMsg("Variable and reason are required");
      setMsgType("error");
      return;
    }
    const binIds = overrideBinIds
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (overrideAction === "merge_bins" && binIds.length < 2) {
      setMsg("merge_bins requires at least 2 source bin IDs (comma-separated)");
      setMsgType("error");
      return;
    }
    const entry: Record<string, unknown> = {
      variable: overrideVar,
      action: overrideAction,
      reason: overrideReason,
      source_bin_ids: binIds,
    };
    if (overrideLabel) entry["new_label"] = overrideLabel;
    setDraftOverrides((prev) => [...prev, entry]);
    setOverrideVar("");
    setOverrideBinIds("");
    setOverrideReason("");
    setOverrideLabel("");
    setMsg(null);
  };

  const removeOverride = (idx: number) => {
    setDraftOverrides((prev) => prev.filter((_, i) => i !== idx));
  };

  const loadedRef = useRef(false);

  useEffect(() => {
    if (editorStateQuery.data && !loadedRef.current) {
      const state = editorStateQuery.data;
      if (state.current_overrides && state.current_overrides.length > 0) {
        setDraftOverrides(state.current_overrides as Record<string, unknown>[]);
      }
      loadedRef.current = true;
    }
  }, [editorStateQuery.data]);

  const es = editorStateQuery.data;
  const isLoading = editorStateQuery.isLoading;

  if (isLoading) {
    return (
      <div style={{ padding: 24, color: "#64748b", fontSize: 13 }}>
        Loading manual binning editor state...
      </div>
    );
  }

  if (!es) {
    return (
      <div style={{ padding: 24, color: "#dc2626", fontSize: 13 }}>
        Could not load editor state.
        <button onClick={onBack} style={linkBtnStyle}>Back</button>
      </div>
    );
  }

  if (!es.ready) {
    return (
      <div style={{ padding: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Manual Bin Editing</h3>
        <div
          style={{
            padding: 16,
            backgroundColor: "#fffbeb",
            border: "1px solid #fde68a",
            borderRadius: 6,
            color: "#92400e",
            fontSize: 13,
          }}
        >
          <strong>Not Ready</strong>
          <p style={{ margin: "8px 0 0 0" }}>{es.blocked_reason}</p>
          {es.required_steps && es.required_steps.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 12, color: "#78350f" }}>
              Required steps: {es.required_steps.join(", ")}
            </div>
          )}
        </div>
        <button onClick={onBack} style={{ ...linkBtnStyle, marginTop: 12 }}>Back to Pathway</button>
      </div>
    );
  }

  // Draft overrides are loaded via useEffect from editor-state data above.

  const previewData: ManualBinningPreviewResponse | undefined = previewMutation.data;

  const selectedVars = es.selected_variables || [];
  const sourceBins = (es.source_bins_by_variable || {}) as Record<string, { bins?: Record<string, unknown>[] }>;

  return (
    <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <button onClick={onBack} style={backBtnStyle}>
          ← Back
        </button>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Manual Bin Editing</h3>
        {es.warnings && es.warnings.length > 0 && (
          <span style={{ fontSize: 11, color: "#f59e0b" }}>
            {es.warnings.length} warning{es.warnings.length > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Source Bins Summary */}
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

      {/* Source Bin Details per Variable */}
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
                      <th style={thStyle}>Bin ID</th>
                      <th style={thStyle}>Lower</th>
                      <th style={thStyle}>Upper</th>
                      <th style={thStyle}>Rows</th>
                      <th style={thStyle}>Good</th>
                      <th style={thStyle}>Bad</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bins.map((b: Record<string, unknown>, i: number) => (
                      <tr key={String(b.bin_id || i)}>
                        <td style={tdStyle}>{String(b.bin_id || "—").slice(0, 16)}</td>
                        <td style={tdStyle}>{b.lower !== undefined ? String(b.lower) : "—"}</td>
                        <td style={tdStyle}>{b.upper !== undefined ? String(b.upper) : "—"}</td>
                        <td style={tdStyle}>{String(b.row_count ?? "—")}</td>
                        <td style={tdStyle}>{String(b.good_count ?? "—")}</td>
                        <td style={tdStyle}>{String(b.bad_count ?? "—")}</td>
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

      {/* Current Draft Overrides */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", marginBottom: 8 }}>
          Overrides ({draftOverrides.length})
        </div>
        {draftOverrides.length === 0 && (
          <div style={{ color: "#94a3b8", fontSize: 12 }}>No overrides yet. Add one below.</div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {draftOverrides.map((o, i) => (
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
                onClick={() => removeOverride(i)}
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

      {/* Add Override Form */}
      <div
        style={{
          padding: 12,
          border: "1px solid #dbeafe",
          borderRadius: 6,
          backgroundColor: "#eff6ff",
          marginBottom: 16,
        }}
      >
        <div style={{ fontSize: 12, fontWeight: 600, color: "#1e40af", marginBottom: 8 }}>
          Add Override
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <label style={{ fontSize: 11, color: "#64748b", flex: 1 }}>
              Variable
              <select
                value={overrideVar}
                onChange={(e) => setOverrideVar(e.target.value)}
                style={inputStyle}
              >
                <option value="">—</option>
                {selectedVars.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </label>
            <label style={{ fontSize: 11, color: "#64748b", flex: 1 }}>
              Action
              <select
                value={overrideAction}
                onChange={(e) => setOverrideAction(e.target.value)}
                style={inputStyle}
              >
                <option value="merge_bins">Merge Bins</option>
                <option value="group_categories">Group Categories</option>
                <option value="isolate_missing">Isolate Missing</option>
                <option value="isolate_special_value">Isolate Special Value</option>
              </select>
            </label>
          </div>
          <label style={{ fontSize: 11, color: "#64748b" }}>
            Source Bin IDs (comma-separated)
            <input
              type="text"
              value={overrideBinIds}
              onChange={(e) => setOverrideBinIds(e.target.value)}
              style={inputStyle}
              placeholder="bin_0, bin_1, bin_2"
            />
          </label>
          <label style={{ fontSize: 11, color: "#64748b" }}>
            New Label (optional, for merge/group)
            <input
              type="text"
              value={overrideLabel}
              onChange={(e) => setOverrideLabel(e.target.value)}
              style={inputStyle}
              placeholder="e.g. Combined Low-Risk"
            />
          </label>
          <label style={{ fontSize: 11, color: "#64748b" }}>
            Reason (required)
            <input
              type="text"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
              style={inputStyle}
              placeholder="Why this override is needed"
            />
          </label>
          <button onClick={addOverride} style={addBtnStyle}>
            Add Override
          </button>
        </div>
      </div>

      {/* Message */}
      {msg && (
        <div
          style={{
            padding: "8px 12px",
            borderRadius: 4,
            fontSize: 12,
            marginBottom: 12,
            backgroundColor: msgType === "error" ? "#fef2f2" : msgType === "success" ? "#f0fdf4" : "#eff6ff",
            color: msgType === "error" ? "#dc2626" : msgType === "success" ? "#166534" : "#3b82f6",
            border: `1px solid ${msgType === "error" ? "#fecaca" : msgType === "success" ? "#bbf7d0" : "#bfdbfe"}`,
          }}
        >
          {msg}
        </div>
      )}

      {/* Preview Results */}
      {previewData && (
        <div
          style={{
            marginBottom: 16,
            padding: 12,
            border: `1px solid ${previewData.valid ? "#bbf7d0" : "#fecaca"}`,
            borderRadius: 6,
            backgroundColor: previewData.valid ? "#f0fdf4" : "#fef2f2",
          }}
        >
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: previewData.valid ? "#166534" : "#dc2626",
              marginBottom: 6,
            }}
          >
            {previewData.valid ? "Preview Passed" : "Preview Failed"}
          </div>
          {previewData.diagnostics?.warnings &&
            previewData.diagnostics.warnings.length > 0 && (
            <div style={{ fontSize: 11, color: "#dc2626", marginBottom: 6 }}>
              {previewData.diagnostics.warnings.map((w, i) => (
                <div key={i}>• {w}</div>
              ))}
            </div>
          )}
          {previewData.valid &&
            previewData.refined_bins_by_variable &&
            Object.keys(previewData.refined_bins_by_variable).length > 0 && (
            <details>
              <summary style={{ cursor: "pointer", fontSize: 11, color: "#166534" }}>
                Show refined bins
              </summary>
              <pre
                style={{
                  marginTop: 8,
                  padding: 8,
                  backgroundColor: "#fff",
                  border: "1px solid #e2e8f0",
                  borderRadius: 4,
                  fontSize: 10,
                  maxHeight: 300,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(previewData.refined_bins_by_variable, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => {
            setMsg(null);
            previewMutation.mutate(draftOverrides);
          }}
          disabled={previewMutation.isPending || draftOverrides.length === 0}
          style={{
            padding: "8px 16px",
            borderRadius: 4,
            border: "1px solid #3b82f6",
            backgroundColor: previewMutation.isPending ? "#eff6ff" : "#fff",
            color: "#3b82f6",
            fontSize: 12,
            fontWeight: 600,
            cursor: previewMutation.isPending || draftOverrides.length === 0 ? "not-allowed" : "pointer",
          }}
        >
          {previewMutation.isPending ? "Previewing..." : "Preview"}
        </button>
        <button
          onClick={() => {
            setMsg(null);
            saveMutation.mutate(draftOverrides);
          }}
          disabled={saveMutation.isPending || draftOverrides.length === 0}
          style={{
            padding: "8px 16px",
            borderRadius: 4,
            border: "none",
            backgroundColor: saveMutation.isPending ? "#93c5fd" : "#3b82f6",
            color: "#fff",
            fontSize: 12,
            fontWeight: 600,
            cursor: saveMutation.isPending || draftOverrides.length === 0 ? "not-allowed" : "pointer",
          }}
        >
          {saveMutation.isPending ? "Saving..." : "Save Overrides"}
        </button>
      </div>

      {es.warnings && es.warnings.length > 0 && (
        <div style={{ marginTop: 12 }}>
          {es.warnings.map((w: Record<string, unknown>, i: number) => (
            <div
              key={i}
              style={{
                padding: "4px 8px",
                backgroundColor: "#fffbeb",
                border: "1px solid #fde68a",
                borderRadius: 4,
                fontSize: 11,
                color: "#92400e",
                marginBottom: 4,
              }}
            >
              {String(w.message || JSON.stringify(w))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left",
  fontSize: 10,
  fontWeight: 600,
  color: "#64748b",
  padding: "2px 6px",
};

const tdStyle: React.CSSProperties = {
  fontSize: 10,
  color: "#334155",
  padding: "2px 6px",
  borderBottom: "1px solid #f1f5f9",
};

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 2,
  padding: "4px 8px",
  border: "1px solid #d1d5db",
  borderRadius: 4,
  fontSize: 12,
  boxSizing: "border-box",
};

const backBtnStyle: React.CSSProperties = {
  padding: "4px 12px",
  borderRadius: 4,
  border: "1px solid #e2e8f0",
  backgroundColor: "#fff",
  color: "#475569",
  fontSize: 12,
  cursor: "pointer",
};

const addBtnStyle: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: 4,
  border: "none",
  backgroundColor: "#3b82f6",
  color: "#fff",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  alignSelf: "flex-start",
};

const linkBtnStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "#3b82f6",
  fontSize: 12,
  cursor: "pointer",
  textDecoration: "underline",
};
