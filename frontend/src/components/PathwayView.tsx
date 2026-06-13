import React from "react";
import type { StepStatus } from "../types";
import { STEP_DISPLAY_METADATA, SECTION_ORDER } from "../config/stepDisplayMetadata";
import { StepCard } from "./StepCard";

interface Props {
  steps: StepStatus[];
  selectedStepId: string | null;
  onStepSelect: (stepId: string) => void;
}

export function PathwayView({ steps, selectedStepId, onStepSelect }: Props) {
  const stepsBySection: Record<string, StepStatus[]> = {};
  for (const step of steps) {
    const meta = STEP_DISPLAY_METADATA[step.step_id];
    const section = meta?.section ?? "Other";
    if (!stepsBySection[section]) stepsBySection[section] = [];
    stepsBySection[section].push(step);
  }

  const orderedSections = SECTION_ORDER.filter((s) => stepsBySection[s]?.length);

  return (
    <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
      {orderedSections.map((section) => (
        <div key={section} style={{ marginBottom: 20 }}>
          <h3
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "#64748b",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              marginBottom: 8,
              paddingBottom: 4,
              borderBottom: "1px solid #e2e8f0",
            }}
          >
            {section}
          </h3>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
              gap: 8,
            }}
          >
            {stepsBySection[section].map((step) => (
              <StepCard
                key={step.step_id}
                step={step}
                isSelected={selectedStepId === step.step_id}
                onSelect={onStepSelect}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
