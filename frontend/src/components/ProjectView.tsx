import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ApiError, api } from "../api/client";
import { pageCardStyle, theme } from "../styles";

interface Props {
  projectPath: string;
  projectId: string;
  onBack: () => void;
}

export function ProjectView({ projectPath, projectId, onBack }: Props) {
  const queryClient = useQueryClient();
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [newPlanName, setNewPlanName] = useState("Scorecard Pathway");
  const [error, setError] = useState<string | null>(null);

  const projectOptions = useMemo(() => ({ projectPath }), [projectPath]);

  const projectQuery = useQuery({
    queryKey: ["project", projectPath, projectId],
    queryFn: () => api.getProject(projectOptions, projectId),
  });

  const plansQuery = useQuery({
    queryKey: ["plans", projectPath, projectId],
    queryFn: () => api.listPlans(projectOptions, projectId),
  });

  const effectiveSelectedPlanId =
    selectedPlanId && plansQuery.data?.plans.some((plan) => plan.plan_id === selectedPlanId)
      ? selectedPlanId
      : (plansQuery.data?.plans[0]?.plan_id ?? null);

  const versionsQuery = useQuery({
    queryKey: ["planVersions", projectPath, projectId, effectiveSelectedPlanId],
    queryFn: () =>
      api.listPlanVersions(projectOptions, projectId, effectiveSelectedPlanId as string),
    enabled: !!effectiveSelectedPlanId,
  });

  const planVersions = versionsQuery.data?.versions ?? [];

  const effectiveSelectedVersionId =
    selectedVersionId &&
    planVersions.some((version) => version.plan_version_id === selectedVersionId)
      ? selectedVersionId
      : (planVersions[planVersions.length - 1]?.plan_version_id ?? null);

  const runsQuery = useQuery({
    queryKey: ["runs", projectPath, projectId],
    queryFn: () => api.listRuns(projectOptions, projectId),
  });

  const runsForSelectedVersion = useMemo(
    () =>
      runsQuery.data?.runs.filter((run) => run.plan_version_id === effectiveSelectedVersionId) ??
      [],
    [runsQuery.data, effectiveSelectedVersionId],
  );

  const effectiveSelectedRunId =
    selectedRunId && runsForSelectedVersion.some((run) => run.run_id === selectedRunId)
      ? selectedRunId
      : (runsForSelectedVersion[0]?.run_id ?? null);

  const selectedRunQuery = useQuery({
    queryKey: ["run", projectPath, projectId, effectiveSelectedRunId],
    queryFn: () => api.getRun(projectOptions, projectId, effectiveSelectedRunId as string),
    enabled: !!effectiveSelectedRunId,
  });

  const runStepsQuery = useQuery({
    queryKey: ["runSteps", projectPath, projectId, effectiveSelectedRunId],
    queryFn: () => api.listRunSteps(projectOptions, projectId, effectiveSelectedRunId as string),
    enabled: !!effectiveSelectedRunId,
  });

  const runEvidenceQuery = useQuery({
    queryKey: ["runEvidence", projectPath, projectId, effectiveSelectedRunId],
    queryFn: () => api.listRunEvidence(projectOptions, projectId, effectiveSelectedRunId as string),
    enabled: !!effectiveSelectedRunId,
  });

  const createPlanMutation = useMutation({
    mutationFn: () => api.createPlan(projectOptions, projectId, { name: newPlanName.trim() }),
    onSuccess: (plan) => {
      setError(null);
      setSelectedPlanId(plan.plan_id);
      setSelectedVersionId(null);
      setSelectedRunId(null);
      queryClient.invalidateQueries({ queryKey: ["plans", projectPath, projectId] });
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.detail : err instanceof Error ? err.message : String(err),
      );
    },
  });

  const runMutation = useMutation({
    mutationFn: () =>
      api.createRun(projectOptions, projectId, {
        plan_version_id: effectiveSelectedVersionId as string,
        force: false,
        sync: true,
      }),
    onSuccess: (run) => {
      setError(null);
      setSelectedRunId(run.run_id);
      queryClient.invalidateQueries({ queryKey: ["runs", projectPath, projectId] });
      queryClient.invalidateQueries({ queryKey: ["run", projectPath, projectId, run.run_id] });
      queryClient.invalidateQueries({ queryKey: ["runSteps", projectPath, projectId, run.run_id] });
      queryClient.invalidateQueries({
        queryKey: ["runEvidence", projectPath, projectId, run.run_id],
      });
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.detail : err instanceof Error ? err.message : String(err),
      );
    },
  });

  const selectedPlan =
    plansQuery.data?.plans.find((plan) => plan.plan_id === effectiveSelectedPlanId) ?? null;
  const selectedVersion =
    versionsQuery.data?.versions.find(
      (version) => version.plan_version_id === effectiveSelectedVersionId,
    ) ?? null;
  const latestError = selectedRunQuery.data?.latest_error as
    | { message?: string; code?: string }
    | null
    | undefined;
  const queryError =
    projectQuery.error ??
    plansQuery.error ??
    versionsQuery.error ??
    runsQuery.error ??
    selectedRunQuery.error ??
    runStepsQuery.error ??
    runEvidenceQuery.error;

  const queryErrorMessage = queryError
    ? queryError instanceof ApiError
      ? queryError.detail
      : queryError instanceof Error
        ? queryError.message
        : String(queryError)
    : null;

  return (
    <main
      style={{
        minHeight: "100vh",
        background: theme.canvas,
        padding: 20,
        fontFamily: theme.fontSans,
      }}
    >
      <div style={{ maxWidth: 1400, margin: "0 auto", display: "grid", gap: 16 }}>
        <header
          style={{
            ...pageCardStyle,
            padding: 18,
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "center",
          }}
        >
          <div>
            <button
              type="button"
              onClick={onBack}
              style={{
                border: `1px solid ${theme.border}`,
                background: theme.surface,
                borderRadius: 999,
                padding: "7px 12px",
                cursor: "pointer",
                color: theme.textSoft,
                marginBottom: 10,
              }}
            >
              Back
            </button>
            <h1 style={{ margin: 0, fontFamily: theme.fontSerif, fontSize: 28 }}>
              {projectQuery.data?.name ?? "Project"}
            </h1>
            <p style={{ margin: "6px 0 0", color: theme.muted, fontSize: 13 }}>{projectPath}</p>
          </div>
          <div style={{ textAlign: "right", color: theme.muted, fontSize: 13 }}>
            <div>{projectQuery.data?.cardre_version ?? ""}</div>
            <div>
              {plansQuery.data?.plans.length ?? 0} plans · {runsQuery.data?.runs.length ?? 0} runs
            </div>
          </div>
        </header>

        {error && (
          <div
            style={{ ...pageCardStyle, padding: 14, background: theme.redBg, color: theme.redText }}
          >
            {error}
          </div>
        )}

        {queryErrorMessage && (
          <div
            style={{
              ...pageCardStyle,
              padding: 14,
              background: theme.yellowBg,
              color: theme.yellowText,
            }}
          >
            {queryErrorMessage}
          </div>
        )}

        <section
          style={{
            display: "grid",
            gridTemplateColumns: "320px minmax(0, 1fr)",
            gap: 16,
            alignItems: "start",
          }}
        >
          <aside style={{ ...pageCardStyle, padding: 16, display: "grid", gap: 16 }}>
            <div>
              <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Plans</h2>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!newPlanName.trim()) return;
                  createPlanMutation.mutate();
                }}
                style={{ display: "grid", gap: 8, marginBottom: 12 }}
              >
                <input
                  value={newPlanName}
                  onChange={(event) => setNewPlanName(event.target.value)}
                  placeholder="New plan name"
                  style={{
                    width: "100%",
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: `1px solid ${theme.borderStrong}`,
                    boxSizing: "border-box",
                  }}
                />
                <button
                  type="submit"
                  disabled={createPlanMutation.isPending}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: 0,
                    background: theme.text,
                    color: "#fff",
                    cursor: createPlanMutation.isPending ? "not-allowed" : "pointer",
                  }}
                >
                  {createPlanMutation.isPending ? "Creating..." : "Create plan"}
                </button>
              </form>

              <div style={{ display: "grid", gap: 8 }}>
                {plansQuery.isLoading ? (
                  <div style={{ color: theme.muted, fontSize: 14 }}>Loading plans...</div>
                ) : plansQuery.data?.plans.length ? (
                  plansQuery.data.plans.map((plan) => (
                    <button
                      key={plan.plan_id}
                      type="button"
                      onClick={() => {
                        setSelectedPlanId(plan.plan_id);
                        setSelectedVersionId(null);
                        setSelectedRunId(null);
                      }}
                      style={{
                        textAlign: "left",
                        padding: 12,
                        borderRadius: 12,
                        border: `1px solid ${plan.plan_id === effectiveSelectedPlanId ? theme.text : theme.border}`,
                        background:
                          plan.plan_id === effectiveSelectedPlanId
                            ? theme.canvasSoft
                            : theme.surface,
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>{plan.name}</div>
                      <div style={{ color: theme.muted, fontSize: 12 }}>{plan.plan_id}</div>
                    </button>
                  ))
                ) : (
                  <div style={{ color: theme.muted, fontSize: 14 }}>No plans yet.</div>
                )}
              </div>
            </div>

            <div>
              <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Runs</h2>
              <div style={{ display: "grid", gap: 8 }}>
                {(runsForSelectedVersion.length
                  ? runsForSelectedVersion
                  : (runsQuery.data?.runs ?? [])
                ).map((run) => (
                  <button
                    key={run.run_id}
                    type="button"
                    onClick={() => setSelectedRunId(run.run_id)}
                    style={{
                      textAlign: "left",
                      padding: 12,
                      borderRadius: 12,
                      border: `1px solid ${run.run_id === effectiveSelectedRunId ? theme.text : theme.border}`,
                      background:
                        run.run_id === effectiveSelectedRunId ? theme.canvasSoft : theme.surface,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{run.status}</div>
                    <div style={{ color: theme.muted, fontSize: 12 }}>{run.run_id}</div>
                  </button>
                ))}
              </div>
            </div>
          </aside>

          <section style={{ display: "grid", gap: 16 }}>
            <div
              style={{
                ...pageCardStyle,
                padding: 18,
                display: "flex",
                justifyContent: "space-between",
                gap: 16,
                alignItems: "center",
              }}
            >
              <div>
                <h2 style={{ margin: 0, fontSize: 18 }}>{selectedPlan?.name ?? "Select a plan"}</h2>
                <p style={{ margin: "6px 0 0", color: theme.muted, fontSize: 13 }}>
                  {selectedVersion
                    ? `Version ${selectedVersion.version_number} · ${selectedVersion.is_committed ? "committed" : "draft"}`
                    : "Choose a plan version to run."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => runMutation.mutate()}
                disabled={!selectedVersion?.is_committed || runMutation.isPending}
                style={{
                  padding: "10px 14px",
                  borderRadius: 10,
                  border: 0,
                  background:
                    !selectedVersion?.is_committed || runMutation.isPending
                      ? theme.mutedSoft
                      : theme.text,
                  color: "#fff",
                  cursor:
                    !selectedVersion?.is_committed || runMutation.isPending
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                {runMutation.isPending
                  ? "Running..."
                  : selectedVersion?.is_committed
                    ? "Run selected version"
                    : "Commit version to run"}
              </button>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
                gap: 16,
              }}
            >
              <section style={{ ...pageCardStyle, padding: 18 }}>
                <h3 style={{ marginTop: 0, fontSize: 16 }}>Plan Versions</h3>
                {versionsQuery.isLoading ? (
                  <div style={{ color: theme.muted }}>Loading versions...</div>
                ) : versionsQuery.data?.versions.length ? (
                  <div style={{ display: "grid", gap: 10 }}>
                    {versionsQuery.data.versions
                      .slice()
                      .reverse()
                      .map((version) => (
                        <button
                          key={version.plan_version_id}
                          type="button"
                          onClick={() => {
                            setSelectedVersionId(version.plan_version_id);
                            setSelectedRunId(null);
                          }}
                          style={{
                            textAlign: "left",
                            padding: 12,
                            borderRadius: 12,
                            border: `1px solid ${version.plan_version_id === effectiveSelectedVersionId ? theme.text : theme.border}`,
                            background:
                              version.plan_version_id === effectiveSelectedVersionId
                                ? theme.canvasSoft
                                : theme.surface,
                            cursor: "pointer",
                          }}
                        >
                          <div
                            style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
                          >
                            <strong>Version {version.version_number}</strong>
                            <span
                              style={{
                                color: version.is_committed ? theme.greenText : theme.yellowText,
                              }}
                            >
                              {version.is_committed ? "Committed" : "Draft"}
                            </span>
                          </div>
                          <div style={{ color: theme.muted, fontSize: 12, marginTop: 4 }}>
                            {version.description || version.plan_version_id}
                          </div>
                        </button>
                      ))}
                  </div>
                ) : (
                  <div style={{ color: theme.muted }}>No versions found.</div>
                )}
              </section>

              <section style={{ ...pageCardStyle, padding: 18 }}>
                <h3 style={{ marginTop: 0, fontSize: 16 }}>Run Details</h3>
                {selectedRunQuery.isLoading ? (
                  <div style={{ color: theme.muted }}>Loading run...</div>
                ) : selectedRunQuery.data ? (
                  <div style={{ display: "grid", gap: 10, fontSize: 14 }}>
                    <div>
                      <strong>Status:</strong> {selectedRunQuery.data.status}
                    </div>
                    <div>
                      <strong>Started:</strong> {selectedRunQuery.data.started_at}
                    </div>
                    <div>
                      <strong>Finished:</strong> {selectedRunQuery.data.finished_at ?? "-"}
                    </div>
                    <div>
                      <strong>Steps:</strong> {selectedRunQuery.data.step_count}
                    </div>
                    <div>
                      <strong>Executed:</strong>{" "}
                      {selectedRunQuery.data.executed_step_ids?.length ?? 0}
                    </div>
                    {latestError && (
                      <div
                        style={{
                          padding: 12,
                          borderRadius: 10,
                          background: theme.redBg,
                          color: theme.redText,
                        }}
                      >
                        {latestError.message ?? latestError.code ?? "Unknown error"}
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ color: theme.muted }}>Select a run to inspect.</div>
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
                <h3 style={{ marginTop: 0, fontSize: 16 }}>Run Steps</h3>
                {runStepsQuery.isLoading ? (
                  <div style={{ color: theme.muted }}>Loading run steps...</div>
                ) : runStepsQuery.data?.length ? (
                  <div style={{ display: "grid", gap: 10 }}>
                    {runStepsQuery.data.map((step) => (
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
                {runEvidenceQuery.isLoading ? (
                  <div style={{ color: theme.muted }}>Loading evidence...</div>
                ) : runEvidenceQuery.data?.length ? (
                  <div style={{ display: "grid", gap: 10 }}>
                    {runEvidenceQuery.data.map((edge) => (
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
          </section>
        </section>
      </div>
    </main>
  );
}
