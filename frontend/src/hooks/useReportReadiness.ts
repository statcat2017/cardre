import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ReportReadinessResponse } from "../types";

export function useReportReadiness(
  projectId: string | null,
  runId: string | null,
  targetBranchId: string | null,
  reportMode: "branch" | "champion" = "branch",
  opts?: { enabled?: boolean },
) {
  return useQuery<ReportReadinessResponse>({
    queryKey: ["reportReadiness", projectId, runId, targetBranchId, reportMode],
    queryFn: () =>
      api.getReportReadiness(projectId!, runId!, {
        target_branch_id: targetBranchId!,
        report_mode: reportMode,
      }),
    enabled: !!projectId && !!runId && !!targetBranchId && (opts?.enabled ?? true),
    staleTime: 5000,
  });
}
