import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, toErrorMessage, type ProjectScope } from "../api/client";
import { useSelectedEntity } from "./useSelectedEntity";

const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "cancelled", "interrupted"]);

function isTerminalRun(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}

export function useProjectWorkspace(scope: ProjectScope) {
  const queryClient = useQueryClient();
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [newPlanName, setNewPlanName] = useState("Scorecard Pathway");
  const [error, setError] = useState<string | null>(null);

  const scoped = api.forProject(scope);

  const projectQuery = useQuery({
    queryKey: ["project", scope.projectId],
    queryFn: () => api.getProject(scope.projectId),
  });

  const plansQuery = useQuery({
    queryKey: ["plans", scope.projectId],
    queryFn: () => scoped.listPlans(),
  });

  const effectiveSelectedPlanId = useSelectedEntity(
    selectedPlanId,
    plansQuery.data?.plans,
    "plan_id",
    "first",
  );

  const versionsQuery = useQuery({
    queryKey: ["planVersions", scope.projectId, effectiveSelectedPlanId],
    queryFn: () => scoped.listPlanVersions(effectiveSelectedPlanId!),
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
    queryKey: ["runs", scope.projectId],
    queryFn: () => scoped.listRuns(),
  });

  const allRuns = runsQuery.data?.runs ?? [];

  const visibleRuns = effectiveSelectedVersionId
    ? allRuns.filter((run) => run.plan_version_id === effectiveSelectedVersionId)
    : allRuns;

  const effectiveSelectedRunId = useSelectedEntity(selectedRunId, visibleRuns, "run_id", "first");

  const selectedRunQuery = useQuery({
    queryKey: ["run", scope.projectId, effectiveSelectedRunId],
    queryFn: () => scoped.getRun(effectiveSelectedRunId!),
    enabled: !!effectiveSelectedRunId,
  });

  const runStepsQuery = useQuery({
    queryKey: ["runSteps", scope.projectId, effectiveSelectedRunId],
    queryFn: () => scoped.listRunSteps(effectiveSelectedRunId!),
    enabled: !!effectiveSelectedRunId,
  });

  const runEvidenceQuery = useQuery({
    queryKey: ["runEvidence", scope.projectId, effectiveSelectedRunId],
    queryFn: () => scoped.listRunEvidence(effectiveSelectedRunId!),
    enabled: !!effectiveSelectedRunId,
  });

  const selectedRunStatus = selectedRunQuery.data?.status;

  useEffect(() => {
    const runId = effectiveSelectedRunId;
    if (!runId || !selectedRunStatus || isTerminalRun(selectedRunStatus)) {
      return;
    }

    const refresh = () => {
      void Promise.all([
        queryClient.refetchQueries({ queryKey: ["runs", scope.projectId] }),
        queryClient.refetchQueries({ queryKey: ["run", scope.projectId, runId] }),
        queryClient.refetchQueries({ queryKey: ["runSteps", scope.projectId, runId] }),
        queryClient.refetchQueries({ queryKey: ["runEvidence", scope.projectId, runId] }),
      ]);
    };

    const intervalId = window.setInterval(refresh, 1_000);
    return () => window.clearInterval(intervalId);
  }, [effectiveSelectedRunId, selectedRunStatus, queryClient, scope.projectId]);

  const createPlanMutation = useMutation({
    mutationFn: () => scoped.createPlan({ name: newPlanName.trim() }),
    onSuccess: (plan) => {
      setError(null);
      setSelectedPlanId(plan.plan_id);
      setSelectedVersionId(null);
      setSelectedRunId(null);
      queryClient.invalidateQueries({ queryKey: ["plans", scope.projectId] });
    },
    onError: (err) => {
      setError(toErrorMessage(err));
    },
  });

  const runMutation = useMutation({
    mutationFn: () =>
      scoped.createRun({
        plan_version_id: effectiveSelectedVersionId!,
        force: false,
        sync: false,
      }),
    onSuccess: (run) => {
      setError(null);
      setSelectedRunId(run.run_id);
      queryClient.invalidateQueries({ queryKey: ["runs", scope.projectId] });
      queryClient.invalidateQueries({ queryKey: ["run", scope.projectId, run.run_id] });
      queryClient.invalidateQueries({ queryKey: ["runSteps", scope.projectId, run.run_id] });
      queryClient.invalidateQueries({ queryKey: ["runEvidence", scope.projectId, run.run_id] });
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

  return {
    projectQuery,
    plansQuery,
    versionsQuery,
    runsQuery,
    selectedRunQuery,
    runStepsQuery,
    runEvidenceQuery,
    effectiveSelectedPlanId,
    effectiveSelectedVersionId,
    effectiveSelectedRunId,
    selectedPlan,
    selectedVersion,
    planVersions,
    visibleRuns,
    newPlanName,
    setNewPlanName,
    error,
    setError,
    queryErrorMessage,
    setSelectedPlanId,
    setSelectedVersionId,
    setSelectedRunId,
    createPlanMutation,
    runMutation,
  };
}
