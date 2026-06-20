import React from "react";
import type { StepStatus } from "../types";
import { getStepDisplayMetadata } from "../config/stepDisplayMetadata";
import { StatusBadge } from "./StatusBadge";
import { theme } from "../styles";

interface Props {
  step: StepStatus;
  isSelected: boolean;
  onSelect: (stepId: string) => void;
  carriedForward?: boolean;
  liveStatus?: string | null;
}

export function StepCard({ step, isSelected, onSelect, carriedForward, liveStatus }: Props) {
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
        backgroundColor: isSelected ? theme.surface : step.is_stale ? theme.yellowBg : theme.surface,
        cursor: "pointer",
        position: "relative",
        transition: "border-color 0.2s, box-shadow 0.2s, transform 0.2s",
        boxShadow: isSelected ? "0 2px 8px rgba(0,0,0,0.04)" : "none",
      }}
    >
      {step.is_stale && (
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
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2, color: theme.text }}>{label}</div>
      <div style={{ fontSize: 12, color: theme.muted, marginBottom: 10, lineHeight: 1.45 }}>{shortDesc}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <StatusBadge status={liveStatus ?? step.status} />
        <span style={{ fontSize: 10, color: theme.mutedSoft, fontFamily: theme.fontMono }}>
          {step.step_id}
        </span>
      </div>
    </div>
  );
}
