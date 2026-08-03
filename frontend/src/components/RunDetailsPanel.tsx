import type { components } from "../api/schema.d";
import { theme, pageCardStyle } from "../styles";

type Run = components["schemas"]["RunResponse"];
type Step = components["schemas"]["RunStepResponse"];
type Evidence = components["schemas"]["RunEvidenceEdgeResponse"];
type Report = components["schemas"]["ReportResponse"];
type Export = components["schemas"]["ExportResponse"];

interface Props {
  runLoading: boolean;
  run: Run | null | undefined;
  stepsLoading: boolean;
  steps: Step[] | null | undefined;
  evidenceLoading: boolean;
  evidence: Evidence[] | null | undefined;
  reportsLoading: boolean;
  reports: Report[] | null | undefined;
  exportsLoading: boolean;
  exports: Export[] | null | undefined;
}

function FileList({
  title,
  loading,
  items,
  renderLine,
}: {
  title: string;
  loading: boolean;
  items: Array<{ id: string; type: string; path: string }> | null | undefined;
  renderLine?: (item: { id: string; type: string; path: string }) => React.ReactNode;
}) {
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>
      {loading ? (
        <div style={{ color: theme.muted }}>Loading...</div>
      ) : items?.length ? (
        items.map((item) => (
          <div
            key={item.id}
            style={{
              padding: 12,
              borderRadius: 12,
              border: `1px solid ${theme.border}`,
              background: theme.canvasSoft,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <strong>{item.type}</strong>
              {renderLine?.(item)}
            </div>
            <div style={{ color: theme.muted, fontSize: 12, marginTop: 4 }}>{item.path}</div>
          </div>
        ))
      ) : (
        <div style={{ color: theme.muted }}>None.</div>
      )}
    </div>
  );
}

export function RunDetailsPanel({
  runLoading,
  run,
  stepsLoading,
  steps,
  evidenceLoading,
  evidence,
  reportsLoading,
  reports,
  exportsLoading,
  exports,
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
                role="alert"
              >
                <strong>{run.latest_error.code}</strong>: {run.latest_error.message}
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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <section style={{ ...pageCardStyle, padding: 18 }}>
          <FileList
            title="Reports"
            loading={reportsLoading}
            items={reports?.map((r) => ({
              id: r.report_id,
              type: r.report_type,
              path: r.path,
            }))}
          />
        </section>
        <section style={{ ...pageCardStyle, padding: 18 }}>
          <FileList
            title="Exports"
            loading={exportsLoading}
            items={exports?.map((e) => ({
              id: e.export_id,
              type: e.export_type,
              path: e.path,
              ...(e.size_bytes ? { size: e.size_bytes } : {}),
            }))}
            renderLine={(item) =>
              "size" in item && typeof item.size === "number" ? (
                <span style={{ color: theme.muted, fontSize: 12 }}>
                  {Math.round(item.size / 1024)} KB
                </span>
              ) : undefined
            }
          />
        </section>
      </div>
    </>
  );
}
