import React from "react";
import type { StepStatus } from "../types";
import { getStepDisplayMetadata } from "../config/stepDisplayMetadata";
import { StatusBadge } from "./StatusBadge";

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
        border: `1px solid ${isSelected ? "#3b82f6" : step.is_stale ? "#f59e0b" : "#e2e8f0"}`,
        borderRadius: 6,
        padding: "10px 12px",
        backgroundColor: isSelected ? "#eff6ff" : step.is_stale ? "#fffbeb" : "#fff",
        cursor: "pointer",
        position: "relative",
        transition: "border-color 0.15s",
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
            backgroundColor: "#f59e0b",
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
            color: "#6366f1",
            backgroundColor: "#eef2ff",
            padding: "1px 6px",
            borderRadius: 8,
            lineHeight: "14px",
          }}
        >
          Carried forward
        </span>
      )}
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>{shortDesc}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <StatusBadge status={liveStatus ?? step.status} />
        <span style={{ fontSize: 10, color: "#94a3b8", fontFamily: "monospace" }}>
          {step.step_id}
        </span>
      </div>
    </div>
  );
}
