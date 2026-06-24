import React from "react";
import { useStepEvidence } from "../../hooks/useStepEvidence";
import { theme } from "../../styles";
import { EvidenceCard } from "./EvidenceCard";
import { ManualBinningEvidenceCard } from "./ManualBinningEvidenceCard";
import type { RunStepEvidenceItem } from "../../types";

interface Props {
  runId: string | null;
  stepId: string;
  projectId: string;
  tab: string;
  planId?: string;
}

export function EvidenceTab({ runId, stepId, projectId, tab, planId }: Props) {
  const isManualBinning = stepId.includes("manual-binning");
  const { data, isLoading, isError, error } = useStepEvidence(
    projectId,
    runId,
    tab === "evidence" ? stepId : null,
  );

  // Manual-binning review card (shown above evidence items)
  const mbCard = isManualBinning && planId ? (
    <ManualBinningEvidenceCard projectId={projectId} planId={planId} stepId={stepId} />
  ) : null;

  // 1. No run yet
  if (!runId) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {mbCard}
        <div style={{ fontSize: 12, color: theme.muted, padding: 10 }}>
          No run yet — evidence is produced when this step runs.
        </div>
      </div>
    );
  }

  // 2. Loading
  if (isLoading) {
    return (
      <div style={{ fontSize: 12, color: theme.muted, padding: 10 }}>
        Loading evidence…
      </div>
    );
  }

  // 3. Load failed
  if (isError) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {mbCard}
        <div
          style={{
            padding: 12, border: `1px solid ${theme.border}`, borderRadius: 8,
            backgroundColor: theme.redBg, fontSize: 13, color: theme.redText,
          }}
        >
          <strong>Evidence could not be loaded.</strong>{" "}
          {error instanceof Error ? error.message : "Unknown error"}
        </div>
      </div>
    );
  }

  // 4. No evidence (response-level status is MISSING)
  if (!data || (data.items ?? []).length === 0 || data.status === "missing") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {mbCard}
        <div style={{ fontSize: 12, color: theme.muted, padding: 10 }}>
          No evidence found for this step.
        </div>
      </div>
    );
  }

  // 5. Stale — all items stale
  if (data.status === "stale") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {mbCard}
        <div
          style={{
            padding: 10, fontSize: 12, color: theme.yellowText,
            backgroundColor: theme.yellowBg, borderRadius: 6,
          }}
        >
          Evidence is stale — upstream inputs have changed.
        </div>
        {(data.items ?? []).map((item: RunStepEvidenceItem) => (
          <EvidenceCard key={item.artifact_id} item={item} />
        ))}
      </div>
    );
  }

  // 6. Partial
  if (data.status === "partial") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {mbCard}
        <div
          style={{
            padding: 10, fontSize: 12, color: theme.yellowText,
            backgroundColor: theme.yellowBg, borderRadius: 6,
          }}
        >
          Partial evidence — some expected artifacts are missing or unsupported.
        </div>
        {(data.items ?? []).map((item: RunStepEvidenceItem) => (
          <EvidenceCard key={item.artifact_id} item={item} />
        ))}
      </div>
    );
  }

  // 7. Available
  const evidenceItems = data.items ?? [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {mbCard}
      {evidenceItems.length > 1 && (
        <div style={{ fontSize: 11, color: theme.muted, padding: "0 2px" }}>
          {evidenceItems.length} evidence artifact{evidenceItems.length !== 1 ? "s" : ""}
        </div>
      )}
      {evidenceItems.map((item: RunStepEvidenceItem) => (
        <EvidenceCard key={item.artifact_id} item={item} />
      ))}
    </div>
  );
}
