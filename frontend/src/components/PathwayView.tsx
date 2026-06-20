import React from "react";
import type { StepStatus } from "../types";
import { STEP_DISPLAY_METADATA, SECTION_ORDER } from "../config/stepDisplayMetadata";
import { StepCard } from "./StepCard";
import { theme } from "../styles";

interface Props {
  steps: StepStatus[];
  selectedStepId: string | null;
  onStepSelect: (stepId: string) => void;
  carriedForwardSteps?: Record<string, boolean>;
  liveStepStatus?: Record<string, string>;
}

export function PathwayView({ steps, selectedStepId, onStepSelect, carriedForwardSteps, liveStepStatus }: Props) {
  const stepsBySection: Record<string, StepStatus[]> = {};
  for (const step of steps) {
    const meta = STEP_DISPLAY_METADATA[step.step_id];
    const section = meta?.section ?? "Other";
    if (!stepsBySection[section]) stepsBySection[section] = [];
    stepsBySection[section].push(step);
  }

  const orderedSections = SECTION_ORDER.filter((s) => stepsBySection[s]?.length);

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1, backgroundColor: theme.canvas }}>
      {orderedSections.map((section) => (
        <div key={section} style={{ marginBottom: 28 }}>
          <h3
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: theme.muted,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              marginBottom: 12,
              paddingBottom: 6,
              borderBottom: `1px solid ${theme.border}`,
            }}
          >
            {section}
          </h3>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
              gap: 12,
            }}
          >
            {stepsBySection[section].map((step) => (
              <StepCard
                key={step.step_id}
                step={step}
                isSelected={selectedStepId === step.step_id}
                onSelect={onStepSelect}
                carriedForward={carriedForwardSteps?.[step.step_id]}
                liveStatus={liveStepStatus?.[step.step_id]}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
