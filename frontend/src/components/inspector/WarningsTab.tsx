import React from "react";
import type { WorkflowBlocker } from "../../types";
import { theme } from "../../styles";

interface Props {
  blockers: WorkflowBlocker[];
  stepFailed?: boolean;
}

export function WarningsTab({ blockers, stepFailed }: Props) {
  const hasItems = blockers.length > 0 || stepFailed;

  if (!hasItems) {
    return (
      <div style={{ fontSize: 12, color: theme.muted, padding: 8 }}>
        No warnings or blockers for this step.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {stepFailed && (
        <div
          style={{
            padding: 10,
            border: `1px solid ${theme.redBg}`,
            borderRadius: 6,
            backgroundColor: theme.redBg,
            fontSize: 11,
            color: theme.redText,
          }}
        >
          <strong>Execution failed</strong>
          <div style={{ marginTop: 4 }}>
            The most recent run of this step did not complete successfully. Check run history for
            details.
          </div>
        </div>
      )}
      {blockers.map((b) => (
        <div
          key={b.code}
          style={{
            padding: 10,
            border: `1px solid ${b.severity === "blocker" ? theme.redBg : theme.yellowBg}`,
            borderRadius: 6,
            backgroundColor: b.severity === "blocker" ? theme.redBg : theme.yellowBg,
            fontSize: 11,
          }}
        >
          <div
            style={{
              fontWeight: 600,
              color: b.severity === "blocker" ? theme.redText : theme.yellowText,
              marginBottom: 2,
            }}
          >
            {b.code}
          </div>
          <div style={{ color: theme.textSoft }}>{b.message}</div>
        </div>
      ))}
    </div>
  );
}
