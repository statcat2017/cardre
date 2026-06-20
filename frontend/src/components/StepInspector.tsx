import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { StepStatus } from "../types";
import { getStepDisplayMetadata } from "../config/stepDisplayMetadata";
import { StatusBadge } from "./StatusBadge";
import { SchemaDrivenParamsEditor } from "./params/SchemaDrivenParamsEditor";
import type { UpdateStepParamsResponse } from "../types";
import { theme } from "../styles";

interface Props {
  step: StepStatus | null;
  planId: string | null;
  projectId: string | null;
  basePlanVersionId: string | null;
  currentParams: Record<string, unknown>;
  onPlanRefreshed: (detailOrResp: UpdateStepParamsResponse | { latest_version_id?: string }) => void;
  onEditManualBinning: (stepId: string) => void;
}

export function StepInspector({
  step,
  planId,
  projectId,
  basePlanVersionId,
  currentParams,
  onPlanRefreshed,
  onEditManualBinning,
}: Props) {
  const [showParams, setShowParams] = useState(false);

  if (!step) {
    return (
      <div
        style={{
          width: 320,
          borderLeft: `1px solid ${theme.border}`,
          backgroundColor: theme.canvasSoft,
          padding: 20,
          flexShrink: 0,
          overflowY: "auto",
        }}
      >
        <div style={{ color: theme.muted, fontSize: 13 }}>Select a step to inspect</div>
      </div>
    );
  }

  const meta = getStepDisplayMetadata(step.step_id);
  const label = meta?.label ?? step.step_id;
  const isManualBinning = step.node_type === "cardre.manual_binning";
  const canEdit = !!planId && !!projectId && !!basePlanVersionId;

  // Only fetch editor state for manual-binning
  const editorStateQuery = useQuery({
    queryKey: ["manualBinningEditorState", planId, projectId, step.step_id],
    queryFn: () =>
      isManualBinning && planId && projectId
        ? api.getManualBinningEditorState(planId, projectId, step.step_id)
        : Promise.reject("not manual-binning"),
    enabled: isManualBinning && !!planId && !!projectId,
    retry: false,
  });

  const mbState = isManualBinning ? editorStateQuery.data : null;

  return (
    <div
      style={{
        width: 320,
        borderLeft: `1px solid ${theme.border}`,
        backgroundColor: theme.canvasSoft,
        padding: 20,
        flexShrink: 0,
        overflowY: "auto",
      }}
    >
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 14, color: theme.text }}>{label}</h3>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <InspectorField label="Step ID" value={step.step_id} mono />
        <InspectorField label="Node Type" value={step.node_type} mono />
        <InspectorField label="Category" value={step.category} />
        <InspectorField label="Backend Position" value={String(step.position)} />

        <div style={{ marginTop: 4 }}>
          <div style={{ fontSize: 11, color: theme.muted, marginBottom: 2 }}>Status</div>
          <StatusBadge status={step.status} />
        </div>

        {step.is_stale && (
          <div
            style={{
              padding: "6px 8px",
              backgroundColor: theme.yellowBg,
              border: `1px solid ${theme.border}`,
              borderRadius: 4,
              fontSize: 11,
              color: theme.yellowText,
            }}
          >
            Stale - upstream has changed since last run
          </div>
        )}

        {meta && (
          <>
            <InspectorField label="Section" value={meta.section} />
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 11, color: theme.muted, marginBottom: 2 }}>Description</div>
              <div style={{ fontSize: 12, color: theme.textSoft }}>{meta.shortDescription}</div>
            </div>
          </>
        )}

        {/* Manual Binning Special Section */}
        {isManualBinning && (
          <div
            style={{
              marginTop: 8,
              padding: 12,
              border: `1px solid ${theme.border}`,
              borderRadius: 8,
              backgroundColor: theme.surface,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: theme.text, marginBottom: 6 }}>
              Manual Bin Editing
            </div>
            {editorStateQuery.isLoading && (
              <div style={{ fontSize: 11, color: theme.muted }}>Loading editor state...</div>
            )}
            {editorStateQuery.isError && (
              <div style={{ fontSize: 11, color: theme.redText }}>Error loading editor state</div>
            )}
            {mbState && !mbState.ready && (
              <div
                style={{
                  padding: "6px 8px",
                  backgroundColor: theme.yellowBg,
                  border: `1px solid ${theme.border}`,
                  borderRadius: 4,
                  fontSize: 11,
                  color: theme.yellowText,
                }}
              >
                <strong>Not Ready</strong>
                <div style={{ marginTop: 4 }}>{mbState.blocked_reason}</div>
                {mbState.required_steps && mbState.required_steps.length > 0 && (
                  <div style={{ marginTop: 4, color: theme.yellowText }}>
                    Need: {mbState.required_steps.join(", ")}
                  </div>
                )}
              </div>
            )}
            {mbState?.ready && (
              <>
                <div style={{ fontSize: 11, color: theme.greenText, marginBottom: 6 }}>
                  {mbState.selected_variables?.length || 0} variables selected, ready to edit.
                </div>
                <button
                  onClick={() => onEditManualBinning(step.step_id)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 4,
                    border: `1px solid ${theme.text}`,
                    backgroundColor: theme.surface,
                    color: theme.text,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Edit Bins
                </button>
              </>
            )}
          </div>
        )}

        {/* Params Editor Section */}
        {canEdit && (
          <div style={{ marginTop: 8 }}>
            <button
              onClick={() => setShowParams(!showParams)}
              style={{
                display: "block",
                width: "100%",
                padding: "6px 10px",
                borderRadius: 4,
                border: `1px solid ${theme.border}`,
                backgroundColor: showParams ? theme.blueBg : theme.surface,
                color: showParams ? theme.blueText : theme.textSoft,
                fontSize: 12,
                fontWeight: 500,
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              {showParams ? "- Hide Parameters" : "+ Configure Parameters"}
            </button>
            {showParams && (
              <SchemaDrivenParamsEditor
                planId={planId!}
                stepId={step.step_id}
                projectId={projectId!}
                currentParams={currentParams}
                basePlanVersionId={basePlanVersionId!}
                nodeType={step.node_type}
                onSaved={onPlanRefreshed}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function InspectorField({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: theme.muted, marginBottom: 2 }}>{label}</div>
      <div
        style={{
          fontSize: 12,
          color: theme.text,
          fontFamily: mono ? theme.fontMono : undefined,
          wordBreak: "break-all",
        }}
      >
        {value}
      </div>
    </div>
  );
}
