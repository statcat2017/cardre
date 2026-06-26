import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function useSelectedBranch(projectId: string) {
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const initialized = useRef(false);

  const { data: branchData } = useQuery({
    queryKey: ["projectBranches", projectId],
    queryFn: () => api.listBranches(projectId, { status: "active" }),
    enabled: !!projectId,
  });

  useEffect(() => {
    if (!initialized.current && !selectedBranchId && branchData?.branches?.length) {
      const baseline = branchData.branches.find((b: { branch_type?: string }) => b.branch_type === "baseline");
      setSelectedBranchId((baseline ?? branchData.branches[0]).branch_id);
      initialized.current = true;
    }
  }, [selectedBranchId, branchData]);

  return { selectedBranchId, setSelectedBranchId, branchData };
}
