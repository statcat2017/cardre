import React from "react";
import type { StepStatus } from "../types";
import { StepCard } from "./StepCard";

interface Props {
  steps: StepStatus[];
}

export function StepCardGrid({ steps }: Props) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: 12,
      }}
    >
      {steps.map((step) => (
        <StepCard key={step.step_id} step={step} />
      ))}
    </div>
  );
}
