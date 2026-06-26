import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function useProjectPlanState(projectId: string) {
  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });

  const { data: projectPlans } = useQuery({
    queryKey: ["projectPlans", projectId],
    queryFn: () => api.getProjectPlans(projectId),
    enabled: !!projectId,
  });

  const scorecardPlan = projectPlans?.plans?.find((p: { is_default?: boolean }) => p.is_default);
  const planId = scorecardPlan?.plan_id ?? null;

  const { data: planData, refetch: refetchPlan } = useQuery({
    queryKey: ["plan", planId],
    queryFn: () => api.getPlan(planId!, projectId),
    enabled: !!planId,
  });

  return {
    project,
    projectLoading,
    projectPlans,
    scorecardPlan,
    planId,
    planData,
    refetchPlan,
  };
}
