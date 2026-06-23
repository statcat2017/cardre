import React, { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ManualBinningEditorStateResponse, ManualBinningPreviewResponse, ManualBinningVariableSummary } from "../types";
import { backButtonStyle, linkButtonStyle, theme } from "../styles";
import { useMessage } from "../hooks/useMessage";
import { MessageBanner } from "./MessageBanner";
import { SourceBinsChips } from "./SourceBinsChips";
import { BinDetailsAccordion } from "./BinDetailsAccordion";
import { OverridesList } from "./OverridesList";
import { AddOverrideForm } from "./AddOverrideForm";
import { PreviewResults } from "./PreviewResults";

interface Props {
  planId: string;
  projectId: string;
  basePlanVersionId: string;
  stepId?: string;
  onBack: () => void;
  onPlanRefreshed: (detail: { latest_version_id?: string }) => void;
}

export function ManualBinningEditor({
  planId,
  projectId,
  basePlanVersionId,
  stepId = "manual-binning",
  onBack,
  onPlanRefreshed,
}: Props) {
  const queryClient = useQueryClient();
  const { msg, msgType, clearMsg, setError, setInfo, setSuccess } = useMessage();

  const editorStateQuery = useQuery({
    queryKey: ["manualBinningEditorState", planId, projectId, stepId],
    queryFn: () => api.getManualBinningEditorState(planId, projectId, stepId),
    enabled: !!planId && !!projectId,
  });

  const [overrideVar, setOverrideVar] = useState("");
  const [overrideAction, setOverrideAction] = useState("merge_bins");
  const [overrideBinIds, setOverrideBinIds] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideLabel, setOverrideLabel] = useState("");
  const [draftOverrides, setDraftOverrides] = useState<Record<string, unknown>[]>([]);

  const previewMutation = useMutation({
    mutationFn: (overrides: Record<string, unknown>[]) =>
      api.previewManualBinning(planId, {
        project_id: projectId,
        plan_version_id: basePlanVersionId,
        overrides,
      }, stepId),
  });

  const saveMutation = useMutation({
    mutationFn: (overrides: Record<string, unknown>[]) =>
      api.updateStepParams(planId, stepId, {
        project_id: projectId,
        base_plan_version_id: basePlanVersionId,
        params: { overrides },
      }),
    onSuccess: () => {
      setSuccess("Manual binning overrides saved.");
      loadedRef.current = false;
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState", planId, projectId] });
    },
    onError: (err: any) => {
      if (err?.status === 409 && err?.detail?.code === "STALE_VERSION") {
        setInfo("Plan was modified externally. Refreshing editor state…");
        loadedRef.current = false;
        queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState", planId, projectId] });
        onPlanRefreshed(err.detail);
      } else if (err?.status === 422) {
        setError(err?.detail?.message || "Validation failed");
      } else {
        setError(err?.message || "Save failed");
      }
    },
  });

  const addOverride = () => {
    if (!overrideVar || !overrideReason) {
      setError("Variable and reason are required");
      return;
    }
    const binIds = overrideBinIds
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (overrideAction === "merge_bins" && binIds.length < 2) {
      setError("merge_bins requires at least 2 source bin IDs (comma-separated)");
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
    clearMsg();
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
      <div style={{ padding: 24, color: theme.muted, fontSize: 13 }}>
        Loading manual binning editor state...
      </div>
    );
  }

  if (!es) {
    return (
      <div style={{ padding: 24, color: theme.redText, fontSize: 13 }}>
        Could not load editor state.
        <button onClick={onBack} style={linkButtonStyle}>Back</button>
      </div>
    );
  }

  if (!es.ready) {
    return (
      <div style={{ padding: 24 }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: theme.text }}>Manual Bin Editing</h3>
        <div
          style={{
            padding: 16,
            backgroundColor: theme.yellowBg,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            color: theme.yellowText,
            fontSize: 13,
          }}
        >
          <strong>Not Ready</strong>
          <p style={{ margin: "8px 0 0 0" }}>{es.blocked_reason}</p>
          {es.required_steps && es.required_steps.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 12, color: theme.yellowText }}>
              Required steps: {es.required_steps.join(", ")}
            </div>
          )}
        </div>
        <button onClick={onBack} style={{ ...linkButtonStyle, marginTop: 12 }}>Back to Pathway</button>
      </div>
    );
  }

  const previewData: ManualBinningPreviewResponse | undefined = previewMutation.data;

  const selectedVars = es.selected_variables || [];
  const sourceBins = (es.source_bins_by_variable || {}) as Record<string, { bins?: Record<string, unknown>[] }>;

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <button onClick={onBack} style={backButtonStyle}>
          Back
        </button>
        <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0, color: theme.text }}>Manual Bin Editing</h3>
      {/* Review Section */}
      <div style={{ marginTop: 16, padding: 16, border: `1px solid ${theme.border}`, borderRadius: 8, backgroundColor: theme.surfaceMuted }}>
        <h4 style={{ fontSize: 13, fontWeight: 600, margin: "0 0 8px 0", color: theme.text }}>Bin Review</h4>
        <p style={{ fontSize: 11, color: theme.textSoft, margin: "0 0 12px 0" }}>
          Confirm that you have reviewed the automated bins. This is a required governance step before the scorecard can be exported.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => {
              clearMsg();
              api.reviewManualBinning(planId, stepId, {
                project_id: projectId,
                plan_version_id: basePlanVersionId,
                step_id: stepId,
                reviewed: true,
                accept_automated: false,
                overrides: draftOverrides.length > 0 ? draftOverrides : undefined,
              }).then(() => {
                setSuccess("Manual binning review complete.");
                queryClient.invalidateQueries({ queryKey: ["plan"] });
                queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState", planId, projectId] });
                queryClient.invalidateQueries({ queryKey: ["workflowGuidance"] });
              }).catch((e: any) => {
                setError(e.message || "Review failed");
              });
            }}
            style={{
              padding: "8px 16px", borderRadius: 4, border: "none",
              backgroundColor: theme.text, color: "#fff", fontSize: 12,
              fontWeight: 600, cursor: saveMutation.isPending ? "not-allowed" : "pointer",
            }}
          >
            Mark bin review complete
          </button>
          <button
            onClick={() => {
              clearMsg();
              api.reviewManualBinning(planId, stepId, {
                project_id: projectId,
                plan_version_id: basePlanVersionId,
                step_id: stepId,
                reviewed: false,
                accept_automated: true,
              }).then(() => {
                setSuccess("Automated bins accepted.");
                queryClient.invalidateQueries({ queryKey: ["plan"] });
                queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState", planId, projectId] });
                queryClient.invalidateQueries({ queryKey: ["workflowGuidance"] });
              }).catch((e: any) => {
                setError(e.message || "Accept failed");
              });
            }}
            style={{
              padding: "8px 16px", borderRadius: 4, border: `1px solid ${theme.border}`,
              backgroundColor: theme.surface, color: theme.textSoft, fontSize: 12,
              fontWeight: 500, cursor: saveMutation.isPending ? "not-allowed" : "pointer",
            }}
          >
            Accept automated bins
          </button>
        </div>
      </div>

      {es.warnings && es.warnings.length > 0 && (
          <span style={{ fontSize: 11, color: theme.yellowText }}>
            {es.warnings.length} warning{es.warnings.length > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Variable Summary Panel */}
      {es.variable_summaries && es.variable_summaries.length > 0 && (
        <div style={{ marginBottom: 16, border: `1px solid ${theme.border}`, borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "8px 12px", backgroundColor: theme.surfaceMuted, borderBottom: `1px solid ${theme.border}`, fontSize: 11, fontWeight: 600, color: theme.text }}>
            Variable Summary
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ backgroundColor: theme.canvasSoft }}>
                  <th style={thStyle}>Variable</th>
                  <th style={thStyle}>IV</th>
                  <th style={thStyle}>Missing</th>
                  <th style={thStyle}>Special</th>
                  <th style={thStyle}>Sparse</th>
                  <th style={thStyle}>Non-mono</th>
                </tr>
              </thead>
              <tbody>
                {es.variable_summaries.map((vs: ManualBinningVariableSummary) => (
                  <tr key={vs.variable} style={{ borderBottom: `1px solid ${theme.border}` }}>
                    <td style={tdStyle}>{vs.variable}</td>
                    <td style={tdStyle}>{vs.iv != null ? vs.iv.toFixed(4) : "—"}</td>
                    <td style={tdStyle}>{vs.missing_count ?? "—"}</td>
                    <td style={tdStyle}>{vs.special_bin_count ?? "—"}</td>
                    <td style={{ ...tdStyle, color: vs.sparse_bin_warning ? theme.yellowText : theme.textSoft }}>
                      {vs.sparse_bin_warning ? "⚠ Yes" : "No"}
                    </td>
                    <td style={{ ...tdStyle, color: vs.non_monotonic_warning ? theme.yellowText : theme.textSoft }}>
                      {vs.non_monotonic_warning ? "⚠ Yes" : "No"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <SourceBinsChips
        selectedVars={selectedVars}
        sourceBins={sourceBins}
        draftOverrides={draftOverrides}
      />

      <BinDetailsAccordion
        selectedVars={selectedVars}
        sourceBins={sourceBins}
        loading={isLoading}
      />

      <OverridesList
        overrides={draftOverrides}
        onRemoveOverride={removeOverride}
      />

      <AddOverrideForm
        overrideVar={overrideVar}
        overrideAction={overrideAction}
        overrideBinIds={overrideBinIds}
        overrideLabel={overrideLabel}
        overrideReason={overrideReason}
        selectedVars={selectedVars}
        onOverrideVarChange={setOverrideVar}
        onOverrideActionChange={setOverrideAction}
        onOverrideBinIdsChange={setOverrideBinIds}
        onOverrideLabelChange={setOverrideLabel}
        onOverrideReasonChange={setOverrideReason}
        onAddOverride={addOverride}
      />

      <MessageBanner message={msg} type={msgType} />

      <PreviewResults previewData={previewData} />

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => {
            clearMsg();
            previewMutation.mutate(draftOverrides);
          }}
          disabled={previewMutation.isPending || draftOverrides.length === 0}
          style={{
            padding: "8px 16px",
            borderRadius: 4,
            border: `1px solid ${theme.text}`,
            backgroundColor: previewMutation.isPending ? theme.canvasSoft : theme.surface,
            color: theme.text,
            fontSize: 12,
            fontWeight: 600,
            cursor: previewMutation.isPending || draftOverrides.length === 0 ? "not-allowed" : "pointer",
          }}
        >
          {previewMutation.isPending ? "Previewing..." : "Preview"}
        </button>
        <button
          onClick={() => {
            clearMsg();
            saveMutation.mutate(draftOverrides);
          }}
          disabled={saveMutation.isPending || draftOverrides.length === 0}
          style={{
            padding: "8px 16px",
            borderRadius: 4,
            border: "none",
            backgroundColor: saveMutation.isPending ? theme.mutedSoft : theme.text,
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
                backgroundColor: theme.yellowBg,
                border: `1px solid ${theme.border}`,
                borderRadius: 4,
                fontSize: 11,
                color: theme.yellowText,
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
  padding: "6px 10px",
  textAlign: "left",
  fontWeight: 600,
  color: theme.muted,
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  borderBottom: `1px solid ${theme.border}`,
};

const tdStyle: React.CSSProperties = {
  padding: "6px 10px",
  color: theme.textSoft,
  fontSize: 11,
};
