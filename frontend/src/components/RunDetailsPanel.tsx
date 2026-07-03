import { theme, pageCardStyle } from "../styles";

interface Run {
  run_id: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  step_count: number;
  executed_step_ids?: string[];
  latest_error?: Record<string, unknown> | null;
}

interface Step {
  run_step_id: string;
  step_id: string;
  status: string;
  plan_version_id: string;
}

interface Evidence {
  evidence_edge_id: string;
  step_id: string;
  policy: string;
  source_label: string;
}

interface Props {
  runLoading: boolean;
  run: Run | null | undefined;
  stepsLoading: boolean;
  steps: Step[] | null | undefined;
  evidenceLoading: boolean;
  evidence: Evidence[] | null | undefined;
}

export function RunDetailsPanel({
  runLoading,
  run,
  stepsLoading,
  steps,
  evidenceLoading,
  evidence,
}: Props) {
  return (
    <>
      <section style={{ ...pageCardStyle, padding: 18 }}>
        <h3 style={{ marginTop: 0, fontSize: 16 }}>Run Details</h3>
        {runLoading ? (
          <div style={{ color: theme.muted }}>Loading run...</div>
        ) : run ? (
          <div style={{ display: "grid", gap: 10, fontSize: 14 }}>
            <div>
              <strong>Status:</strong> {run.status}
            </div>
            <div>
              <strong>Started:</strong> {run.started_at}
            </div>
            <div>
              <strong>Finished:</strong> {run.finished_at ?? "-"}
            </div>
            <div>
              <strong>Steps:</strong> {run.step_count}
            </div>
            <div>
              <strong>Executed:</strong> {run.executed_step_ids?.length ?? 0}
            </div>
            {run.latest_error && (
              <div
                style={{
                  padding: 12,
                  borderRadius: 10,
                  background: theme.redBg,
                  color: theme.redText,
                }}
              >
                {String(run.latest_error.message ?? run.latest_error.code ?? "Unknown error")}
              </div>
            )}
          </div>
        ) : (
          <div style={{ color: theme.muted }}>Select a run to inspect.</div>
        )}
      </section>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <section style={{ ...pageCardStyle, padding: 18 }}>
          <h3 style={{ marginTop: 0, fontSize: 16 }}>Run Steps</h3>
          {stepsLoading ? (
            <div style={{ color: theme.muted }}>Loading run steps...</div>
          ) : steps?.length ? (
            <div style={{ display: "grid", gap: 10 }}>
              {steps.map((step) => (
                <div
                  key={step.run_step_id}
                  style={{
                    padding: 12,
                    borderRadius: 12,
                    border: `1px solid ${theme.border}`,
                    background: theme.canvasSoft,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>{step.step_id}</strong>
                    <span>{step.status}</span>
                  </div>
                  <div style={{ color: theme.muted, fontSize: 12, marginTop: 4 }}>
                    {step.plan_version_id}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ color: theme.muted }}>No run steps.</div>
          )}
        </section>

        <section style={{ ...pageCardStyle, padding: 18 }}>
          <h3 style={{ marginTop: 0, fontSize: 16 }}>Evidence Edges</h3>
          {evidenceLoading ? (
            <div style={{ color: theme.muted }}>Loading evidence...</div>
          ) : evidence?.length ? (
            <div style={{ display: "grid", gap: 10 }}>
              {evidence.map((edge) => (
                <div
                  key={edge.evidence_edge_id}
                  style={{
                    padding: 12,
                    borderRadius: 12,
                    border: `1px solid ${theme.border}`,
                    background: theme.canvasSoft,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>{edge.step_id}</strong>
                    <span>{edge.policy}</span>
                  </div>
                  <div style={{ color: theme.muted, fontSize: 12, marginTop: 4 }}>
                    {edge.source_label}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ color: theme.muted }}>No evidence edges.</div>
          )}
        </section>
      </div>
    </>
  );
}
