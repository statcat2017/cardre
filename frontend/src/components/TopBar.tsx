import React from "react";
import type { ProjectDetailResponse } from "../types";

interface Props {
  project: ProjectDetailResponse;
  planName: string | null;
  running: boolean;
  onRun: () => void;
  canRun: boolean;
}

export function TopBar({ project, planName, running, onRun, canRun }: Props) {
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
          {running ? "Running..." : "Run Pathway"}
        </button>
      </div>
    </div>
  );
}
