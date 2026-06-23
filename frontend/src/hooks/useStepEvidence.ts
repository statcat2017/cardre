import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunStepEvidenceResponse } from "../types";

export function useStepEvidence(
  projectId: string | null,
  runId: string | null,
  stepId: string | null,
) {
  return useQuery<RunStepEvidenceResponse>({
    queryKey: ["step-evidence", projectId, runId, stepId],
    queryFn: () => api.getStepEvidence(runId!, stepId!, projectId!),
    enabled: !!projectId && !!runId && !!stepId,
    staleTime: 30_000,
    retry: false,
  });
}
