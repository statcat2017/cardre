import React from "react";
import type { StepStatus } from "../types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  step: StepStatus;
}

export function StepCard({ step }: Props) {
  return (
    <div
      style={{
        border: `1px solid ${step.is_stale ? "#f59e0b" : "#e5e7eb"}`,
        borderRadius: 8,
        padding: 12,
        backgroundColor: step.is_stale ? "#fffbeb" : "#fff",
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        position: "relative",
      }}
    >
      {step.is_stale && (
        <div
          title="Stale"
          style={{
            position: "absolute",
            top: 4,
            right: 4,
            width: 8,
            height: 8,
            borderRadius: "50%",
            backgroundColor: "#f59e0b",
          }}
        />
      )}
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
        {step.step_id}
      </div>
      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 8 }}>
        {step.node_type} · {step.category}
      </div>
      <StatusBadge status={step.status} />
    </div>
  );
}
