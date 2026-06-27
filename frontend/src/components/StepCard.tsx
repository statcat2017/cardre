import React from "react";
import type { StepStatus, WorkflowStepGuidance, WorkflowBlocker } from "../types";
import { getStepDisplayMetadata } from "../config/stepDisplayMetadata";
import { StatusBadge } from "./StatusBadge";
import { theme } from "../styles";

interface Props {
  step: StepStatus;
  isSelected: boolean;
  onSelect: (stepId: string) => void;
  carriedForward?: boolean;
  liveStatus?: string | null;
  guidanceForStep?: WorkflowStepGuidance | null;
  blockers?: WorkflowBlocker[];
}

export function StepCard({
  step,
  isSelected,
  onSelect,
  carriedForward,
  liveStatus,
  guidanceForStep,
  blockers,
}: Props) {
  const meta = getStepDisplayMetadata(step.step_id);
  const label = meta?.label ?? step.step_id;
  const shortDesc = meta?.shortDescription ?? step.node_type;

  return (
    <div
      onClick={() => onSelect(step.step_id)}
      style={{
        border: `1px solid ${isSelected ? theme.text : step.is_stale ? theme.yellowText : theme.border}`,
        borderRadius: 8,
        padding: "14px 16px",
        backgroundColor: isSelected
          ? theme.surface
          : step.is_stale
            ? theme.yellowBg
            : theme.surface,
        cursor: "pointer",
        position: "relative",
        transition: "border-color 0.2s, box-shadow 0.2s, transform 0.2s",
        boxShadow: isSelected ? "0 2px 8px rgba(0,0,0,0.04)" : "none",
      }}
    >
      {/* Stale dot: guidance-driven readiness row preferred; fallback to legacy dot */}
      {!guidanceForStep && step.is_stale && (
        <div
          title="Stale"
          style={{
            position: "absolute",
            top: 6,
            right: 6,
            width: 8,
            height: 8,
            borderRadius: "50%",
            backgroundColor: theme.yellowText,
          }}
        />
      )}
      {carriedForward && (
        <span
          style={{
            position: "absolute",
            bottom: 6,
            right: 6,
            fontSize: 9,
            fontWeight: 600,
            color: theme.blueText,
            backgroundColor: theme.blueBg,
            padding: "1px 6px",
            borderRadius: 9999,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            lineHeight: "14px",
          }}
        >
          Carried forward
        </span>
      )}
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2, color: theme.text }}>
        {label}
      </div>
      <div style={{ fontSize: 12, color: theme.muted, marginBottom: 10, lineHeight: 1.45 }}>
        {shortDesc}
      </div>
      {/* Readiness row from guidance */}
      {guidanceForStep && (
        <div style={{ marginBottom: 8, fontSize: 11, lineHeight: 1.5 }}>
          {guidanceForStep.readiness === "stale" && (
            <span style={{ color: theme.yellowText }}>▲ Stale — upstream has changed</span>
          )}
          {guidanceForStep.readiness === "needs_config" && (
            <span style={{ color: theme.blueText }}>⚙ Configuration required</span>
          )}
          {guidanceForStep.readiness === "ready" && (
            <span style={{ color: theme.greenText }}>✓ Ready to run</span>
          )}
          {guidanceForStep.readiness === "blocked" && (
            <span style={{ color: theme.redText }}>
              ⊘ Blocked{blockers && blockers.length > 0 ? ` — ${blockers[0].message}` : ""}
            </span>
          )}
          {guidanceForStep.readiness === "complete" && (
            <span style={{ color: theme.greenText }}>✓ Complete</span>
          )}
          {guidanceForStep.evidence_kinds && guidanceForStep.evidence_kinds.length > 0 && (
            <span style={{ color: theme.muted, marginLeft: 8 }}>
              {guidanceForStep.evidence_kinds.length} evidence item
              {guidanceForStep.evidence_kinds.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <StatusBadge status={liveStatus ?? step.status} />
        <span style={{ fontSize: 10, color: theme.mutedSoft, fontFamily: theme.fontMono }}>
          {step.step_id}
        </span>
      </div>
    </div>
  );
}
