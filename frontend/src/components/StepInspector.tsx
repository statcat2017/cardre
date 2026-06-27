import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { StepStatus, UpdateStepParamsResponse, WorkflowGuidance } from "../types";
import { getStepDisplayMetadata, canonicalizeStepId } from "../config/stepDisplayMetadata";
import { theme } from "../styles";
import { NextActionTab } from "./inspector/NextActionTab";
import { ConfigureTab } from "./inspector/ConfigureTab";
import { EvidenceTab } from "./inspector/EvidenceTab";
import { WarningsTab } from "./inspector/WarningsTab";
import { RunHistoryTab } from "./inspector/RunHistoryTab";

type InspectorTab = "next_action" | "configure" | "evidence" | "warnings" | "history";

const TAB_LABELS: Record<InspectorTab, string> = {
  next_action: "Next action",
  configure: "Configure",
  evidence: "Evidence",
  warnings: "Warnings",
  history: "Run history",
};

interface Props {
  step: StepStatus | null;
  planId: string | null;
  projectId: string | null;
  basePlanVersionId: string | null;
  currentParams: Record<string, unknown>;
  onPlanRefreshed: (
    detailOrResp: UpdateStepParamsResponse | { latest_version_id?: string },
  ) => void;
  onEditManualBinning: (stepId: string) => void;
  guidance?: WorkflowGuidance | null;
  runId?: string | null;
}

interface InnerProps {
  step: StepStatus;
  planId: string | null;
  projectId: string | null;
  basePlanVersionId: string | null;
  currentParams: Record<string, unknown>;
  onPlanRefreshed: (
    detailOrResp: UpdateStepParamsResponse | { latest_version_id?: string },
  ) => void;
  onEditManualBinning: (stepId: string) => void;
  guidance?: WorkflowGuidance | null;
  runId: string | null;
}

export function StepInspector({
  step,
  planId,
  projectId,
  basePlanVersionId,
  currentParams,
  onPlanRefreshed,
  onEditManualBinning,
  guidance,
  runId = null,
}: Props) {
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

  return (
    <StepInspectorInner
      key={step.step_id}
      step={step}
      planId={planId}
      projectId={projectId}
      basePlanVersionId={basePlanVersionId}
      currentParams={currentParams}
      onPlanRefreshed={onPlanRefreshed}
      onEditManualBinning={onEditManualBinning}
      guidance={guidance}
      runId={runId}
    />
  );
}

function StepInspectorInner({
  step,
  planId,
  projectId,
  basePlanVersionId,
  currentParams,
  onPlanRefreshed,
  onEditManualBinning,
  guidance,
  runId,
}: InnerProps) {
  const [tab, setTab] = useState<InspectorTab>("next_action");

  const meta = step ? getStepDisplayMetadata(step.step_id) : null;
  const label = meta?.label ?? step?.step_id ?? "";
  const isManualBinning = step?.node_type === "cardre.manual_binning";
  const canEdit = !!planId && !!projectId && !!basePlanVersionId;
  const canonicalId = step ? canonicalizeStepId(step.step_id) : null;
  const guidanceForStep = canonicalId ? guidance?.step_guidance?.[canonicalId] : null;
  const stepBlockers = step
    ? (guidance?.blockers ?? []).filter(
        (b) => b.step_id && canonicalizeStepId(b.step_id) === canonicalId,
      )
    : [];

  const editorStateQuery = useQuery({
    queryKey: ["manualBinningEditorState", planId, projectId, step?.step_id],
    queryFn: () =>
      isManualBinning && planId && projectId
        ? api.getManualBinningEditorState(planId, projectId, step!.step_id)
        : Promise.reject("not manual-binning"),
    enabled: !!step && isManualBinning && !!planId && !!projectId,
  });

  return (
    <div
      style={{
        width: 320,
        borderLeft: `1px solid ${theme.border}`,
        backgroundColor: theme.canvasSoft,
        flexShrink: 0,
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ padding: "16px 16px 8px" }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0, color: theme.text }}>{label}</h3>
        <div style={{ fontSize: 10, color: theme.muted, fontFamily: theme.fontMono, marginTop: 2 }}>
          {step.step_id}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          borderBottom: `1px solid ${theme.border}`,
          padding: "0 8px",
          gap: 0,
        }}
      >
        {(Object.keys(TAB_LABELS) as InspectorTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              flex: 1,
              padding: "6px 4px",
              border: "none",
              borderBottom: `2px solid ${tab === t ? theme.text : "transparent"}`,
              backgroundColor: "transparent",
              color: tab === t ? theme.text : theme.muted,
              fontSize: 10,
              fontWeight: tab === t ? 600 : 400,
              cursor: "pointer",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      <div style={{ padding: 12, flex: 1, overflowY: "auto" }}>
        {tab === "next_action" && (
          <NextActionTab
            guidanceForStep={guidanceForStep}
            isManualBinning={isManualBinning}
            onEditManualBinning={() => onEditManualBinning(step.step_id)}
            manualBinningState={
              (editorStateQuery.data as {
                ready: boolean;
                blocked_reason?: string;
                selected_variables?: string[];
              } | null) ?? null
            }
            loadingManualBinning={editorStateQuery.isLoading}
          />
        )}

        {tab === "configure" && canEdit && (
          <ConfigureTab
            stepId={step.step_id}
            nodeType={step.node_type}
            planId={planId!}
            projectId={projectId!}
            basePlanVersionId={basePlanVersionId!}
            currentParams={currentParams}
            onPlanRefreshed={onPlanRefreshed}
          />
        )}
        {tab === "configure" && !canEdit && (
          <div style={{ fontSize: 12, color: theme.muted }}>Params editing is not available.</div>
        )}

        {tab === "evidence" && (
          <EvidenceTab
            runId={runId}
            stepId={step.step_id}
            projectId={projectId!}
            tab={tab}
            planId={planId ?? undefined}
          />
        )}

        {tab === "warnings" && (
          <WarningsTab blockers={stepBlockers} stepFailed={step.status === "failed"} />
        )}

        {tab === "history" && (
          <RunHistoryTab stepId={step.step_id} projectId={projectId!} runId={runId} tab={tab} />
        )}
      </div>
    </div>
  );
}
