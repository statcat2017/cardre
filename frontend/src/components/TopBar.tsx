import React, { useState } from "react";
import type { ProjectDetailResponse } from "../types";
import { theme } from "../styles";

interface Props {
  project: ProjectDetailResponse;
  planName: string | null;
  running: boolean;
  onRun: () => void;
  canRun: boolean;
  stepProgress?: { completed: number; total: number } | null;
}

export function TopBar({ project, planName, running, onRun, canRun, stepProgress }: Props) {
  const [showHelp, setShowHelp] = useState(false);

  const runLabel = running
    ? stepProgress
      ? `${stepProgress.completed}/${stepProgress.total}`
      : "Running..."
    : "Run Pathway";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        minHeight: 56,
        padding: "0 24px",
        backgroundColor: theme.surface,
        color: theme.text,
        borderBottom: `1px solid ${theme.border}`,
        flexShrink: 0,
        position: "relative",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontFamily: theme.fontSerif, fontWeight: 600, fontSize: 20, letterSpacing: "-0.03em" }}>Cardre</span>
        <span style={{ fontSize: 12, color: theme.mutedSoft }}>/</span>
        <span style={{ fontSize: 13, color: theme.textSoft }}>{project.name}</span>
        {planName && (
          <>
            <span style={{ fontSize: 12, color: theme.mutedSoft }}>/</span>
            <span style={{ fontSize: 12, color: theme.muted }}>{planName}</span>
          </>
        )}
        <button
          onClick={() => setShowHelp(!showHelp)}
          style={{
            background: "none",
            border: `1px solid ${theme.border}`,
            borderRadius: 4,
            width: 18,
            height: 18,
            fontSize: 11,
            lineHeight: "16px",
            textAlign: "center",
            color: theme.muted,
            cursor: "pointer",
            padding: 0,
          }}
          title="About this view"
        >
          ?
        </button>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 11, color: theme.muted, fontFamily: theme.fontMono }}>
          {project.plan_count} plans, {project.run_count} runs
        </span>
        <button
          onClick={onRun}
          disabled={running || !canRun}
          style={{
            padding: "7px 16px",
            borderRadius: 4,
            border: "none",
            backgroundColor: running || !canRun ? theme.mutedSoft : theme.text,
            color: "#fff",
            fontSize: 12,
            fontWeight: 600,
            cursor: running || !canRun ? "not-allowed" : "pointer",
          }}
        >
          {runLabel}
        </button>
      </div>

      {showHelp && (
        <div
          style={{
            position: "absolute",
            top: 56,
            left: 24,
            maxWidth: 400,
            backgroundColor: theme.surface,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            padding: "12px 16px",
            fontSize: 12,
            color: theme.textSoft,
            lineHeight: 1.6,
            zIndex: 100,
            boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
          }}
        >
          <strong>Import vs Scorecard Pathway</strong>
          <p style={{ margin: "4px 0 0", color: theme.muted }}>
            Importing a dataset creates a hidden <code>__import__</code> plan that preserves
            source-data evidence separately. The <strong>Scorecard Pathway</strong> consumes
            the imported artifact and records its own modelling run evidence — the two plans
            remain independent so you can always trace the original source data.
            Import evidence is visible in the Artifacts browser.
          </p>
        </div>
      )}
    </div>
  );
}
