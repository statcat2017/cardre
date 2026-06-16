import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { StepStatus } from "../types";
import { getStepDisplayMetadata } from "../config/stepDisplayMetadata";
import { StatusBadge } from "./StatusBadge";
import { ParamsEditor } from "./ParamsEditor";
import type { UpdateStepParamsResponse } from "../types";

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
          width: 300,
          borderLeft: "1px solid #e2e8f0",
          backgroundColor: "#fafafa",
          padding: 16,
          flexShrink: 0,
          overflowY: "auto",
        }}
      >
        <div style={{ color: "#94a3b8", fontSize: 13 }}>Select a step to inspect</div>
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
        width: 300,
        borderLeft: "1px solid #e2e8f0",
        backgroundColor: "#fafafa",
        padding: 16,
        flexShrink: 0,
        overflowY: "auto",
      }}
    >
      <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>{label}</h3>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <InspectorField label="Step ID" value={step.step_id} mono />
        <InspectorField label="Node Type" value={step.node_type} mono />
        <InspectorField label="Category" value={step.category} />
        <InspectorField label="Backend Position" value={String(step.position)} />

        <div style={{ marginTop: 4 }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 2 }}>Status</div>
          <StatusBadge status={step.status} />
        </div>

        {step.is_stale && (
          <div
            style={{
              padding: "6px 8px",
              backgroundColor: "#fffbeb",
              border: "1px solid #fde68a",
              borderRadius: 4,
              fontSize: 11,
              color: "#92400e",
            }}
          >
            Stale — upstream has changed since last run
          </div>
        )}

        {meta && (
          <>
            <InspectorField label="Section" value={meta.section} />
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 2 }}>Description</div>
              <div style={{ fontSize: 12, color: "#334155" }}>{meta.shortDescription}</div>
            </div>
          </>
        )}

        {/* Manual Binning Special Section */}
        {isManualBinning && (
          <div
            style={{
              marginTop: 8,
              padding: 10,
              border: "1px solid #e2e8f0",
              borderRadius: 6,
              backgroundColor: "#fff",
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", marginBottom: 6 }}>
              Manual Bin Editing
            </div>
            {editorStateQuery.isLoading && (
              <div style={{ fontSize: 11, color: "#64748b" }}>Loading editor state...</div>
            )}
            {editorStateQuery.isError && (
              <div style={{ fontSize: 11, color: "#dc2626" }}>Error loading editor state</div>
            )}
            {mbState && !mbState.ready && (
              <div
                style={{
                  padding: "6px 8px",
                  backgroundColor: "#fffbeb",
                  border: "1px solid #fde68a",
                  borderRadius: 4,
                  fontSize: 11,
                  color: "#92400e",
                }}
              >
                <strong>Not Ready</strong>
                <div style={{ marginTop: 4 }}>{mbState.blocked_reason}</div>
                {mbState.required_steps && mbState.required_steps.length > 0 && (
                  <div style={{ marginTop: 4, color: "#78350f" }}>
                    Need: {mbState.required_steps.join(", ")}
                  </div>
                )}
              </div>
            )}
            {mbState?.ready && (
              <>
                <div style={{ fontSize: 11, color: "#166534", marginBottom: 6 }}>
                  {mbState.selected_variables?.length || 0} variables selected, ready to edit.
                </div>
                <button
                  onClick={() => onEditManualBinning(step.step_id)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 4,
                    border: "1px solid #3b82f6",
                    backgroundColor: "#fff",
                    color: "#3b82f6",
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
                border: "1px solid #e2e8f0",
                backgroundColor: showParams ? "#eff6ff" : "#fff",
                color: showParams ? "#3b82f6" : "#475569",
                fontSize: 12,
                fontWeight: 500,
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              {showParams ? "▼ Hide Parameters" : "▶ Configure Parameters"}
            </button>
            {showParams && (
              <ParamsEditor
                planId={planId!}
                stepId={step.step_id}
                projectId={projectId!}
                currentParams={currentParams}
                basePlanVersionId={basePlanVersionId!}
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
      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 2 }}>{label}</div>
      <div
        style={{
          fontSize: 12,
          color: "#1e293b",
          fontFamily: mono ? "monospace" : undefined,
          wordBreak: "break-all",
        }}
      >
        {value}
      </div>
    </div>
  );
}
