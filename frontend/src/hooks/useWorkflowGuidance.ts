import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { WorkflowGuidance } from "../types";

export function useWorkflowGuidance(
  planId: string | null,
  projectId: string | null,
  branchId: string | null,
  runId?: string | null,
) {
  return useQuery<WorkflowGuidance>({
    queryKey: ["workflowGuidance", projectId, planId, branchId, runId],
    queryFn: () =>
      api.getWorkflowGuidance(planId!, {
        project_id: projectId!,
        ...(branchId ? { branch_id: branchId } : {}),
        ...(runId ? { run_id: runId } : {}),
      }),
    enabled: !!planId && !!projectId && !!branchId,
    staleTime: 2000,
  });
}
