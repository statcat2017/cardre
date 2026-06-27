import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ManualBinningEditorStateResponse } from "../types";

export function useManualBinningState(
  projectId: string,
  planId: string,
  stepId: string,
  planVersionId?: string,
  enabled = true,
) {
  return useQuery<ManualBinningEditorStateResponse>({
    queryKey: ["manualBinningState", projectId, planId, stepId, planVersionId],
    queryFn: () => api.getManualBinningEditorState(planId, projectId, stepId, planVersionId),
    enabled: enabled && !!planId && !!projectId && !!stepId,
    staleTime: 2000,
  });
}
