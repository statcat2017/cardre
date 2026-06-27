import React from "react";
import type { StepStatus, WorkflowGuidance } from "../types";
import {
  STEP_DISPLAY_METADATA,
  SECTION_ORDER,
  canonicalizeStepId,
  sectionPhase,
} from "../config/stepDisplayMetadata";
import { StepCard } from "./StepCard";
import { theme } from "../styles";

interface Props {
  steps: StepStatus[];
  selectedStepId: string | null;
  onStepSelect: (stepId: string) => void;
  carriedForwardSteps?: Record<string, boolean>;
  liveStepStatus?: Record<string, string>;
  guidance?: WorkflowGuidance | null;
}

export function PathwayView({
  steps,
  selectedStepId,
  onStepSelect,
  carriedForwardSteps,
  liveStepStatus,
  guidance,
}: Props) {
  const stepsBySection: Record<string, StepStatus[]> = {};
  for (const step of steps) {
    const canonicalId = canonicalizeStepId(step.step_id);
    const meta = canonicalId ? STEP_DISPLAY_METADATA[canonicalId] : undefined;
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
          {guidance &&
            (() => {
              const sr = sectionPhase(stepsBySection[section], guidance);
              const nextLabel = sr.nextStep
                ? (STEP_DISPLAY_METADATA[sr.nextStep]?.label ?? sr.nextStep)
                : null;
              return (
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      padding: "1px 6px",
                      borderRadius: 3,
                      backgroundColor:
                        sr.phase === "complete"
                          ? theme.greenBg
                          : sr.phase === "blocked"
                            ? theme.redBg
                            : sr.phase === "in_progress"
                              ? theme.yellowBg
                              : "transparent",
                      color:
                        sr.phase === "complete"
                          ? theme.greenText
                          : sr.phase === "blocked"
                            ? theme.redText
                            : sr.phase === "in_progress"
                              ? theme.yellowText
                              : theme.muted,
                    }}
                  >
                    {sr.phase === "not_started"
                      ? "Not started"
                      : sr.phase === "in_progress"
                        ? "In progress"
                        : sr.phase === "complete"
                          ? "Complete"
                          : "Blocked"}
                  </span>
                  <span style={{ fontSize: 10, color: theme.muted }}>
                    {sr.complete}/{sr.total} complete
                    {sr.stale > 0 ? ` · ${sr.stale} stale` : ""}
                    {sr.blocked > 0 ? ` · ${sr.blocked} blocked` : ""}
                  </span>
                  {nextLabel && (
                    <span style={{ fontSize: 10, color: theme.blueText, marginLeft: "auto" }}>
                      Next: {nextLabel}
                    </span>
                  )}
                </div>
              );
            })()}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
              gap: 12,
            }}
          >
            {stepsBySection[section].map((step) => {
              const canonicalId = canonicalizeStepId(step.step_id);
              const sg = guidance?.step_guidance?.[canonicalId];
              const stepBlockers = (guidance?.blockers ?? []).filter(
                (b) => b.step_id && canonicalizeStepId(b.step_id) === canonicalId,
              );
              return (
                <StepCard
                  key={step.step_id}
                  step={step}
                  isSelected={selectedStepId === step.step_id}
                  onSelect={onStepSelect}
                  carriedForward={carriedForwardSteps?.[step.step_id]}
                  liveStatus={liveStepStatus?.[step.step_id]}
                  guidanceForStep={sg ?? null}
                  blockers={stepBlockers}
                />
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
