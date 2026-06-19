import React, { useState } from "react";
import type { ProjectDetailResponse } from "../types";

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
        height: 48,
        padding: "0 16px",
        backgroundColor: "#1e293b",
        color: "#f8fafc",
        flexShrink: 0,
        position: "relative",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontWeight: 700, fontSize: 15 }}>Cardre</span>
        <span style={{ fontSize: 12, color: "#94a3b8" }}>|</span>
        <span style={{ fontSize: 13, color: "#cbd5e1" }}>{project.name}</span>
        {planName && (
          <>
            <span style={{ fontSize: 12, color: "#64748b" }}>|</span>
            <span style={{ fontSize: 12, color: "#94a3b8" }}>{planName}</span>
          </>
        )}
        <button
          onClick={() => setShowHelp(!showHelp)}
          style={{
            background: "none",
            border: "1px solid #475569",
            borderRadius: "50%",
            width: 18,
            height: 18,
            fontSize: 11,
            lineHeight: "16px",
            textAlign: "center",
            color: "#94a3b8",
            cursor: "pointer",
            padding: 0,
          }}
          title="About this view"
        >
          ?
        </button>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 11, color: "#64748b" }}>
          {project.plan_count} plans, {project.run_count} runs
        </span>
        <button
          onClick={onRun}
          disabled={running || !canRun}
          style={{
            padding: "6px 16px",
            borderRadius: 4,
            border: "none",
            backgroundColor: running ? "#64748b" : canRun ? "#22c55e" : "#475569",
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
            top: 48,
            left: 16,
            maxWidth: 400,
            backgroundColor: "#1e293b",
            border: "1px solid #475569",
            borderRadius: 8,
            padding: "12px 16px",
            fontSize: 12,
            color: "#cbd5e1",
            lineHeight: 1.6,
            zIndex: 100,
            boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
          }}
        >
          <strong>Import vs Scorecard Pathway</strong>
          <p style={{ margin: "4px 0 0", color: "#94a3b8" }}>
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
