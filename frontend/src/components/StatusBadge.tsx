import React from "react";
import type { StepStatusCode } from "../types";

const STATUS_COLORS: Record<StepStatusCode, string> = {
  not_run: "#9ca3af",
  queued: "#3b82f6",
  running: "#eab308",
  succeeded: "#22c55e",
  failed: "#ef4444",
  cancelled: "#6b7280",
};

const STATUS_LABELS: Record<StepStatusCode, string> = {
  not_run: "Not Run",
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

interface Props {
  status: StepStatusCode;
}

export function StatusBadge({ status }: Props) {
  const color = STATUS_COLORS[status] || "#9ca3af";
  const label = STATUS_LABELS[status] || status;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 12,
        fontSize: 12,
        fontWeight: 600,
        color: "#fff",
        backgroundColor: color,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: "#fff",
          opacity: 0.8,
          ...(status === "running" ? { animation: "pulse 1s infinite" } : {}),
        }}
      />
      {label}
    </span>
  );
}
