import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BranchListItem } from "../types";
import { theme } from "../styles";

interface Props {
  projectId: string;
  selectedBranchId: string | null;
  onBranchChange: (branchId: string) => void;
}

export function BranchSelector({ projectId, selectedBranchId, onBranchChange }: Props) {
  const { data: branchData } = useQuery({
    queryKey: ["projectBranches", projectId],
    queryFn: () => api.listBranches(projectId, { status: "active" }),
    enabled: !!projectId,
  });

  const branches: BranchListItem[] = branchData?.branches ?? [];

  // Auto-select first branch if none selected
  React.useEffect(() => {
    if (!selectedBranchId && branches.length > 0) {
      onBranchChange(branches[0].branch_id);
    }
  }, [branches, selectedBranchId, onBranchChange]);

  if (branches.length === 0) return null;

  return (
    <div style={{ padding: "8px 24px 0", display: "flex", alignItems: "center", gap: 8 }}>
      <label style={{ fontSize: 11, color: theme.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Branch
      </label>
      <select
        value={selectedBranchId ?? ""}
        onChange={(e) => onBranchChange(e.target.value)}
        style={{
          padding: "4px 8px",
          borderRadius: 4,
          border: `1px solid ${theme.border}`,
          fontSize: 12,
          backgroundColor: theme.surface,
          color: theme.text,
          cursor: "pointer",
        }}
      >
        {branches.map((b) => (
          <option key={b.branch_id} value={b.branch_id}>
            {b.name || b.branch_id.slice(0, 8)}
          </option>
        ))}
      </select>
    </div>
  );
}
