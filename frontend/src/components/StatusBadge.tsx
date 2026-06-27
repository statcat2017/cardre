import React from "react";
import type { StepStatusCode } from "../types";
import { theme } from "../styles";

const STATUS_COLORS: Record<StepStatusCode, { bg: string; text: string }> = {
  not_run: { bg: theme.canvasSoft, text: theme.muted },
  queued: { bg: theme.blueBg, text: theme.blueText },
  running: { bg: theme.yellowBg, text: theme.yellowText },
  succeeded: { bg: theme.greenBg, text: theme.greenText },
  failed: { bg: theme.redBg, text: theme.redText },
  cancelled: { bg: theme.canvasSoft, text: theme.muted },
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
  status: string;
}

export function StatusBadge({ status }: Props) {
  const color = STATUS_COLORS[status as StepStatusCode] || {
    bg: theme.canvasSoft,
    text: theme.muted,
  };
  const label = STATUS_LABELS[status as StepStatusCode] || status;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 9999,
        fontSize: 10,
        fontWeight: 600,
        color: color.text,
        backgroundColor: color.bg,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          backgroundColor: color.text,
          opacity: 0.7,
          ...(status === "running" ? { animation: "pulse 1s infinite" } : {}),
        }}
      />
      {label}
    </span>
  );
}
