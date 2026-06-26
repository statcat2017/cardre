import React, { useState } from "react";
import { useManualBinningState } from "../hooks/useManualBinningState";
import { theme, backButtonStyle, linkButtonStyle } from "../styles";
import { ErrorNotice } from "./ErrorNotice";
import { ManualBinningVariableList } from "./ManualBinningVariableList";
import { ManualBinningReviewPanel } from "./ManualBinningReviewPanel";
import { ManualBinningReviewActions } from "./ManualBinningReviewActions";
import { ManualBinningBinTable } from "./ManualBinningBinTable";
import { ManualBinningEditDialog } from "./ManualBinningEditDialog";

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
  const [stepVersion, setStepVersion] = useState(basePlanVersionId);
  const state = useManualBinningState(projectId, planId, stepId, stepVersion);
  const [selectedVar, setSelectedVar] = useState<string | null>(null);
  const [editingVar, setEditingVar] = useState<string | null>(null);

  const es = state.data;
  const firstVar = selectedVar ?? es?.selected_variables?.[0] ?? null;

  if (state.isLoading) {
    return (
      <div style={{ padding: 24, color: theme.muted, fontSize: 13 }}>
        Loading manual binning editor state…
      </div>
    );
  }

  if (!es) {
    return (
      <div style={{ padding: 24, fontSize: 13 }}>
        <ErrorNotice error={state.error} context="Could not load editor state" />
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

  return (
    <div style={{ display: "flex", gap: 16, padding: 16, overflowY: "auto", flex: 1 }}>
      <ManualBinningVariableList
        summaries={es.variable_summaries || []}
        stepStatus={es.review_status}
        selected={firstVar}
        onSelect={setSelectedVar}
      />
      <div style={{ flex: 2, overflow: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <button onClick={onBack} style={backButtonStyle}>Back</button>
          <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0, color: theme.text }}>Manual Bin Editing</h3>
        </div>
        <ManualBinningReviewPanel variable={firstVar} state={es} />
        <ManualBinningBinTable
          variable={firstVar}
          sourceBins={
            firstVar
              ? (es.source_bins_by_variable as Record<string, any>)?.[firstVar] ?? null
              : null
          }
          summary={firstVar ? es.variable_summaries?.find((v) => v.variable === firstVar) : null}
          onEdit={setEditingVar}
        />
        {editingVar && (
          <ManualBinningEditDialog
            variable={editingVar}
            state={es}
            planId={planId}
            basePlanVersionId={stepVersion}
            stepId={stepId}
            projectId={projectId}
            onClose={() => setEditingVar(null)}
            onSaved={(newPlanVersionId) => {
              setEditingVar(null);
              if (newPlanVersionId) setStepVersion(newPlanVersionId);
            }}
            onPlanRefreshed={(detail) => {
              if (detail.latest_version_id) setStepVersion(detail.latest_version_id);
              onPlanRefreshed(detail);
            }}
          />
        )}
        <ManualBinningReviewActions
          state={es}
          planId={planId}
          stepId={stepId}
          basePlanVersionId={stepVersion}
          onPlanRefreshed={(detail) => {
            if (detail.latest_version_id) setStepVersion(detail.latest_version_id);
            onPlanRefreshed(detail);
          }}
        />
      </div>
    </div>
  );
}
