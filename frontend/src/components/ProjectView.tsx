import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, toErrorMessage } from "../api/client";
import { useSelectedEntity } from "../hooks/useSelectedEntity";
import { theme, pageCardStyle } from "../styles";
import { PlanSidebar } from "./PlanSidebar";
import { RunDetailsPanel } from "./RunDetailsPanel";
import { VersionPanel } from "./VersionPanel";

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

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });

  const plansQuery = useQuery({
    queryKey: ["plans", projectId],
    queryFn: () => api.listPlans({ projectId }, projectId),
  });

  const effectiveSelectedPlanId = useSelectedEntity(
    selectedPlanId,
    plansQuery.data?.plans,
    "plan_id",
    "first",
  );

  const versionsQuery = useQuery({
    queryKey: ["planVersions", projectId, effectiveSelectedPlanId],
    queryFn: () =>
      api.listPlanVersions({ projectId }, projectId, effectiveSelectedPlanId as string),
    enabled: !!effectiveSelectedPlanId,
  });

  const planVersions = versionsQuery.data?.versions ?? [];

  const effectiveSelectedVersionId = useSelectedEntity(
    selectedVersionId,
    planVersions,
    "plan_version_id",
    "last",
  );

  const runsQuery = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns({ projectId }, projectId),
  });

  const runsForSelectedVersion =
    runsQuery.data?.runs.filter((run) => run.plan_version_id === effectiveSelectedVersionId) ?? [];

  const effectiveSelectedRunId = useSelectedEntity(
    selectedRunId,
    runsForSelectedVersion,
    "run_id",
    "first",
  );

  const selectedRunQuery = useQuery({
    queryKey: ["run", projectId, effectiveSelectedRunId],
    queryFn: () => api.getRun({ projectId }, projectId, effectiveSelectedRunId as string),
    enabled: !!effectiveSelectedRunId,
  });

  const runStepsQuery = useQuery({
    queryKey: ["runSteps", projectId, effectiveSelectedRunId],
    queryFn: () => api.listRunSteps({ projectId }, projectId, effectiveSelectedRunId as string),
    enabled: !!effectiveSelectedRunId,
  });

  const runEvidenceQuery = useQuery({
    queryKey: ["runEvidence", projectId, effectiveSelectedRunId],
    queryFn: () => api.listRunEvidence({ projectId }, projectId, effectiveSelectedRunId as string),
    enabled: !!effectiveSelectedRunId,
  });

  const createPlanMutation = useMutation({
    mutationFn: () => api.createPlan({ projectId }, projectId, { name: newPlanName.trim() }),
    onSuccess: (plan) => {
      setError(null);
      setSelectedPlanId(plan.plan_id);
      setSelectedVersionId(null);
      setSelectedRunId(null);
      queryClient.invalidateQueries({ queryKey: ["plans", projectId] });
    },
    onError: (err) => {
      setError(toErrorMessage(err));
    },
  });

  const runMutation = useMutation({
    mutationFn: () =>
      api.createRun({ projectId }, projectId, {
        plan_version_id: effectiveSelectedVersionId as string,
        force: false,
        sync: false,
      }),
    onSuccess: (run) => {
      setError(null);
      setSelectedRunId(run.run_id);
      queryClient.invalidateQueries({ queryKey: ["runs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["run", projectId, run.run_id] });
      queryClient.invalidateQueries({ queryKey: ["runSteps", projectId, run.run_id] });
      queryClient.invalidateQueries({
        queryKey: ["runEvidence", projectId, run.run_id],
      });
    },
    onError: (err) => {
      setError(toErrorMessage(err));
    },
  });

  const selectedPlan =
    plansQuery.data?.plans.find((plan) => plan.plan_id === effectiveSelectedPlanId) ?? null;
  const selectedVersion =
    versionsQuery.data?.versions.find(
      (version) => version.plan_version_id === effectiveSelectedVersionId,
    ) ?? null;

  const queryErrorEntries: Array<{ key: string; error: Error | null }> = [
    { key: "project", error: projectQuery.error },
    { key: "plans", error: plansQuery.error },
    { key: "versions", error: versionsQuery.error },
    { key: "runs", error: runsQuery.error },
    { key: "run", error: selectedRunQuery.error },
    { key: "runSteps", error: runStepsQuery.error },
    { key: "runEvidence", error: runEvidenceQuery.error },
  ];
  const errored = queryErrorEntries.find((e) => e.error);
  const queryErrorMessage = errored ? `[${errored.key}] ${toErrorMessage(errored.error!)}` : null;

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
            style={{
              ...pageCardStyle,
              padding: 14,
              background: theme.redBg,
              color: theme.redText,
            }}
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
          <PlanSidebar
            plans={plansQuery.data?.plans}
            plansLoading={plansQuery.isLoading}
            effectiveSelectedPlanId={effectiveSelectedPlanId}
            onSelectPlan={(planId) => {
              setSelectedPlanId(planId);
              setSelectedVersionId(null);
              setSelectedRunId(null);
            }}
            newPlanName={newPlanName}
            onNewPlanNameChange={setNewPlanName}
            onCreatePlan={() => {
              if (!newPlanName.trim()) return;
              createPlanMutation.mutate();
            }}
            createPlanPending={createPlanMutation.isPending}
            runsForVersion={runsForSelectedVersion}
            allRuns={runsQuery.data?.runs}
            effectiveSelectedRunId={effectiveSelectedRunId}
            onSelectRun={setSelectedRunId}
          />

          <section style={{ display: "grid", gap: 16 }}>
            <VersionPanel
              selectedPlan={selectedPlan}
              selectedVersion={selectedVersion}
              versionsLoading={versionsQuery.isLoading}
              versions={versionsQuery.data?.versions}
              effectiveSelectedVersionId={effectiveSelectedVersionId}
              onSelectVersion={(versionId) => {
                setSelectedVersionId(versionId);
                setSelectedRunId(null);
              }}
              runPending={runMutation.isPending}
              canRun={!!selectedVersion?.is_committed}
              onRun={() => runMutation.mutate()}
            />

            <RunDetailsPanel
              runLoading={selectedRunQuery.isLoading}
              run={selectedRunQuery.data}
              stepsLoading={runStepsQuery.isLoading}
              steps={runStepsQuery.data}
              evidenceLoading={runEvidenceQuery.isLoading}
              evidence={runEvidenceQuery.data}
            />
          </section>
        </section>
      </div>
    </main>
  );
}
