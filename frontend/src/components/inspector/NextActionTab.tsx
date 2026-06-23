import React from "react";
import type { WorkflowStepGuidance } from "../../types";
import { theme } from "../../styles";

interface Props {
  guidanceForStep?: WorkflowStepGuidance | null;
  isManualBinning: boolean;
  onEditManualBinning?: () => void;
  manualBinningState?: { ready: boolean; blocked_reason?: string; selected_variables?: string[] } | null;
  loadingManualBinning?: boolean;
}

export function NextActionTab({ guidanceForStep, isManualBinning, onEditManualBinning, manualBinningState, loadingManualBinning }: Props) {
  return (
    <div style={{ fontSize: 12, color: theme.textSoft, lineHeight: 1.6 }}>
      {guidanceForStep ? (
        <>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, color: theme.muted, marginBottom: 2 }}>Status</div>
            <span style={{
              fontWeight: 600,
              color: guidanceForStep.readiness === "complete" || guidanceForStep.readiness === "ready"
                ? theme.greenText
                : guidanceForStep.readiness === "blocked"
                  ? theme.redText
                  : guidanceForStep.readiness === "stale"
                    ? theme.yellowText
                    : theme.blueText,
            }}>
              {guidanceForStep.readiness === "complete" ? "✓ Complete" :
               guidanceForStep.readiness === "ready" ? "→ Ready" :
               guidanceForStep.readiness === "stale" ? "▲ Stale" :
               guidanceForStep.readiness === "blocked" ? "⊘ Blocked" :
               guidanceForStep.readiness === "needs_config" ? "⚙ Needs configuration" :
               guidanceForStep.readiness}
            </span>
          </div>

          {guidanceForStep.explanation && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: theme.muted, marginBottom: 2 }}>Why this matters</div>
              <div>{guidanceForStep.explanation}</div>
            </div>
          )}

          {guidanceForStep.primary_action && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: theme.muted, marginBottom: 2 }}>Next action</div>
              <div style={{ fontWeight: 600, color: theme.text }}>{guidanceForStep.primary_action}</div>
            </div>
          )}

          {guidanceForStep.evidence_kinds && guidanceForStep.evidence_kinds.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: theme.muted, marginBottom: 4 }}>Evidence required</div>
              {guidanceForStep.evidence_kinds.map((k) => (
                <div key={k} style={{ fontSize: 11, color: theme.textSoft, padding: "2px 0" }}>
                  ✓ {k}
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div style={{ color: theme.muted }}>Select a step to view guidance.</div>
      )}

      {isManualBinning && (
        <div style={{ marginTop: 12, padding: 12, border: `1px solid ${theme.border}`, borderRadius: 8, backgroundColor: theme.surface }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: theme.text, marginBottom: 6 }}>Manual Bin Editing</div>
          {loadingManualBinning && <div style={{ fontSize: 11, color: theme.muted }}>Loading editor state...</div>}
          {manualBinningState && !manualBinningState.ready && (
            <div style={{ padding: "6px 8px", backgroundColor: theme.yellowBg, border: `1px solid ${theme.border}`, borderRadius: 4, fontSize: 11, color: theme.yellowText }}>
              <strong>Not Ready</strong>
              {manualBinningState.blocked_reason && <div style={{ marginTop: 4 }}>{manualBinningState.blocked_reason}</div>}
            </div>
          )}
          {manualBinningState?.ready && (
            <>
              <div style={{ fontSize: 11, color: theme.greenText, marginBottom: 6 }}>
                {(manualBinningState?.selected_variables?.length || _parseNSelected(guidanceForStep?.action_target) || 0)} variables selected, ready to edit.
              </div>
              {onEditManualBinning && (
                <button
                  onClick={onEditManualBinning}
                  style={{
                    padding: "6px 12px", borderRadius: 4, border: `1px solid ${theme.text}`,
                    backgroundColor: theme.surface, color: theme.text, fontSize: 12, fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Edit Bins
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function _parseNSelected(actionTarget: string | null | undefined): number | null {
  if (!actionTarget) return null;
  const match = actionTarget.match(/N_selected=(\d+)/);
  return match ? parseInt(match[1], 10) : null;
}
