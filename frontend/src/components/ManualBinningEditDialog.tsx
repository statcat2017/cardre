import React, { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, isApiError } from "../api/client";
import type { ManualBinningEditorStateResponse } from "../types";
import { theme } from "../styles";
import { useMessage } from "../hooks/useMessage";
import { MessageBanner } from "./MessageBanner";

interface Props {
  variable: string;
  state: ManualBinningEditorStateResponse;
  planId: string;
  basePlanVersionId: string;
  stepId: string;
  projectId: string;
  onClose: () => void;
  onSaved: (newPlanVersionId?: string) => void;
  onPlanRefreshed?: (detail: { latest_version_id?: string }) => void;
}

const REASON_CODES = [
  { value: "business_interpretability", label: "Business interpretability" },
  { value: "monotonicity", label: "Monotonicity" },
  { value: "sparse_bin", label: "Sparse bin" },
  { value: "zero_cell", label: "Zero cell" },
  { value: "missing_value_treatment", label: "Missing value handling" },
  { value: "special_value_treatment", label: "Special value handling" },
  { value: "regulatory_or_policy", label: "Regulatory or policy" },
  { value: "other", label: "Other" },
];

const ACTIONS = [
  { value: "merge_bins", label: "Merge adjacent bins" },
  { value: "group_categories", label: "Group categories" },
  { value: "reject_variable", label: "Reject variable" },
  { value: "reorder_missing_bin", label: "Isolate missing" },
  { value: "reorder_special_bin", label: "Isolate special" },
];

const OVERLAY_STYLE: React.CSSProperties = {
  position: "fixed", inset: 0, backgroundColor: "rgba(0,0,0,0.3)",
  display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
};

const DIALOG_STYLE: React.CSSProperties = {
  backgroundColor: theme.surface, borderRadius: 8, border: `1px solid ${theme.border}`,
  padding: 20, minWidth: 400, maxWidth: 500, boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
};

export function ManualBinningEditDialog({ variable, state, planId, basePlanVersionId, stepId, projectId, onClose, onSaved, onPlanRefreshed }: Props) {
  const queryClient = useQueryClient();
  const { msg, msgType, clearMsg, setError, setSuccess } = useMessage();

  const [action, setAction] = useState("merge_bins");
  const [sourceBinIds, setSourceBinIds] = useState("");
  const [reasonCode, setReasonCode] = useState("");
  const [reasonText, setReasonText] = useState("");
  const [newLabel, setNewLabel] = useState("");

  // Reset preview state whenever form inputs change
  const resetPreview = useCallback(() => {
    previewMutation.reset();
  }, []);

  const handleActionChange = (v: string) => { setAction(v); resetPreview(); };
  const handleBinIdsChange = (v: string) => { setSourceBinIds(v); resetPreview(); };
  const handleReasonCodeChange = (v: string) => { setReasonCode(v); resetPreview(); };
  const handleReasonTextChange = (v: string) => { setReasonText(v); resetPreview(); };
  const handleLabelChange = (v: string) => { setNewLabel(v); resetPreview(); };

  const previewMutation = useMutation({
    mutationFn: (proposedOverride: Record<string, unknown>) =>
      api.previewManualBinning(planId, {
        project_id: projectId,
        plan_version_id: basePlanVersionId,
        overrides: [
          ...((state.current_overrides || []) as Record<string, unknown>[]),
          proposedOverride,
        ],
      }, stepId),
  });

  const saveMutation = useMutation({
    mutationFn: (proposedOverride: Record<string, unknown>) =>
      api.updateStepParams(planId, stepId, {
        project_id: projectId,
        base_plan_version_id: basePlanVersionId,
        params: {
          overrides: [
            ...((state.current_overrides || []) as Record<string, unknown>[]),
            proposedOverride,
          ],
        },
      }),
    onSuccess: (data) => {
      setSuccess("Override saved.");
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningState", projectId, planId, stepId] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState"] });
      onSaved(data?.new_plan_version_id);
    },
    onError: (err: unknown) => {
      if (isApiError(err) && err.status === 409 && err.detail.code === "STALE_VERSION") {
        onPlanRefreshed?.(err.detail);
      } else {
        setError(isApiError(err) ? err.detail.message : "Save failed");
      }
    },
  });

  const revertMutation = useMutation({
    mutationFn: ({ reasonCode: rc, reasonText: rt }: { reasonCode: string; reasonText: string }) => {
      const filteredOverrides = ((state.current_overrides || []) as Record<string, unknown>[])
        .filter((ov) => ov.variable !== variable);
      return api.reviewManualBinning(planId, stepId, {
        project_id: projectId,
        plan_version_id: basePlanVersionId,
        step_id: stepId,
        reviewed: false,
        accept_automated: false,
        overrides: filteredOverrides,
        reason_code: rc,
        review_reason: rt,
      });
    },
    onSuccess: (data) => {
      setSuccess("Reverted to automated bins.");
      queryClient.invalidateQueries({ queryKey: ["plan"] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningState", projectId, planId, stepId] });
      queryClient.invalidateQueries({ queryKey: ["manualBinningEditorState"] });
      onSaved(data?.new_plan_version_id);
    },
    onError: (err: unknown) => {
      if (isApiError(err) && err.status === 409 && err.detail.code === "STALE_VERSION") {
        onPlanRefreshed?.(err.detail);
      } else {
        setError(isApiError(err) ? err.detail.message : "Revert failed");
      }
    },
  });

  const canSave = reasonCode.length > 0 && reasonText.trim().length > 0;
  const hasValidPreview = previewMutation.data?.valid === true;

  function buildOverride(): Record<string, unknown> | null {
    if (!reasonCode || !reasonText) {
      setError("Reason code and reason text are required.");
      return null;
    }
    const binIds = sourceBinIds.split(",").map((s) => s.trim()).filter(Boolean);
    if ((action === "merge_bins" || action === "group_categories") && binIds.length < 2) {
      setError("This action requires at least two source bin IDs.");
      return null;
    }
    const override: Record<string, unknown> = {
      variable,
      action,
      reason_code: reasonCode,
      reason: reasonText,
      source_bin_ids: binIds,
    };
    if (newLabel) override.new_label = newLabel;
    return override;
  }

  const handlePreview = () => {
    clearMsg();
    const override = buildOverride();
    if (!override) return;
    previewMutation.mutate(override);
  };

  const handleSave = () => {
    clearMsg();
    const override = buildOverride();
    if (!override) return;
    saveMutation.mutate(override);
  };

  const handleRevert = () => {
    clearMsg();
    if (!reasonCode || !reasonText) {
      setError("Reason code and text are required to revert.");
      return;
    }
    revertMutation.mutate({ reasonCode, reasonText });
  };

  return (
    <div style={OVERLAY_STYLE} onClick={onClose}>
      <div style={DIALOG_STYLE} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <strong style={{ fontSize: 14, color: theme.text }}>Edit — {variable}</strong>
          <button onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 16 }}>×</button>
        </div>

        <MessageBanner message={msg} type={msgType} />

        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>Action</label>
          <select value={action} onChange={(e) => handleActionChange(e.target.value)} style={selectStyle}>
            {ACTIONS.map((a) => (
              <option key={a.value} value={a.value}>{a.label}</option>
            ))}
          </select>
        </div>

        {(action === "merge_bins" || action === "group_categories") && (
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>Source bin IDs (comma-separated, at least 2)</label>
            <input
              type="text"
              value={sourceBinIds}
              onChange={(e) => handleBinIdsChange(e.target.value)}
              placeholder="e.g. b1, b2"
              style={inputStyle}
            />
          </div>
        )}

        {action === "group_categories" && (
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>New label (optional)</label>
            <input
              type="text"
              value={newLabel}
              onChange={(e) => handleLabelChange(e.target.value)}
              placeholder="New category label"
              style={inputStyle}
            />
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>Reason code</label>
          <select value={reasonCode} onChange={(e) => handleReasonCodeChange(e.target.value)} style={selectStyle}>
            <option value="">Select a reason code…</option>
            {REASON_CODES.map((rc) => (
              <option key={rc.value} value={rc.value}>{rc.label}</option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>Reason</label>
          <textarea
            value={reasonText}
            onChange={(e) => handleReasonTextChange(e.target.value)}
            placeholder="Describe why this edit is needed…"
            rows={2}
            style={{ ...inputStyle, resize: "vertical" }}
          />
        </div>

        {previewMutation.data && previewMutation.data.valid && (
          <div style={{ marginBottom: 12, padding: 8, backgroundColor: theme.greenBg, borderRadius: 4, fontSize: 10, color: theme.greenText }}>
            Preview: {((previewMutation.data.refined_bins_by_variable || {}) as Record<string, any>)[variable]?.bins?.length ?? "?"} bins after edit — preview valid.
          </div>
        )}

        {previewMutation.data && !previewMutation.data.valid && (
          <div style={{ marginBottom: 12, padding: 8, backgroundColor: theme.yellowBg, borderRadius: 4, fontSize: 10, color: theme.yellowText }}>
            Preview invalid: {(previewMutation.data.diagnostics?.warnings || []).join("; ")}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={handlePreview} disabled={!canSave || previewMutation.isPending} style={btnStyle(theme.text, canSave && !previewMutation.isPending)}>
            {previewMutation.isPending ? "Previewing…" : "Preview"}
          </button>
          <button onClick={handleSave} disabled={!canSave || !hasValidPreview || saveMutation.isPending} style={btnStyle(theme.text, canSave && hasValidPreview && !saveMutation.isPending)}>
            {saveMutation.isPending ? "Saving…" : "Save"}
          </button>
          <button onClick={handleRevert} disabled={!canSave || revertMutation.isPending} style={btnStyle(theme.yellowText, canSave && !revertMutation.isPending)}>
            {revertMutation.isPending ? "Reverting…" : "Revert to automated"}
          </button>
          <button onClick={onClose} style={{ ...btnStyle(theme.textSoft, true), border: `1px solid ${theme.border}`, backgroundColor: theme.surface, color: theme.textSoft }}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: "block", fontSize: 10, fontWeight: 600, color: theme.muted,
  textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4,
};

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "6px 8px", border: `1px solid ${theme.borderStrong}`,
  borderRadius: 4, fontSize: 11, color: theme.text, backgroundColor: theme.surface,
  boxSizing: "border-box",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
};

function btnStyle(color: string, enabled: boolean): React.CSSProperties {
  return {
    padding: "6px 14px", borderRadius: 4, border: "none",
    backgroundColor: enabled ? color : theme.mutedSoft,
    color: "#fff", fontSize: 11, fontWeight: 600,
    cursor: enabled ? "pointer" : "not-allowed",
    opacity: enabled ? 1 : 0.5,
  };
}
