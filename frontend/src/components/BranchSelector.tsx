import React from "react";
import type { BranchListItem } from "../types";
import { theme } from "../styles";

interface BranchSelectorProps {
  branches: BranchListItem[];
  selectedBranchId: string | null;
  onSelect?: (branchId: string) => void;
  disabled?: boolean;
}

export function BranchSelector({ branches, selectedBranchId, onSelect, disabled }: BranchSelectorProps) {
  const activeBranches = branches.filter((b) => b.status === "active");
  const selectedBranch = activeBranches.find((b) => b.branch_id === selectedBranchId);

  if (!onSelect) {
    return (
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, color: theme.textSoft, display: "block", marginBottom: 4 }}>
          Target branch
        </label>
        <div style={{ fontSize: 13, color: theme.muted, paddingTop: 6 }}>
          {selectedBranchId && selectedBranch
            ? selectedBranch.name || selectedBranch.branch_id
            : "Select a branch."}
        </div>
      </div>
    );
  }

  return (
    <div>
      <label style={{ fontSize: 12, fontWeight: 600, color: theme.textSoft, display: "block", marginBottom: 4 }}>
        Target branch
      </label>
      <select
        data-testid="branch-select"
        value={selectedBranchId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        disabled={disabled}
        style={{
          padding: "6px 10px", borderRadius: 6, border: `1px solid ${theme.borderStrong}`,
          fontSize: 13, backgroundColor: theme.surface, color: theme.text,
        }}
      >
        {activeBranches.length === 0 && <option value="">No branches available</option>}
        {activeBranches.map((b) => (
          <option key={b.branch_id} value={b.branch_id}>
            {b.name || b.branch_id}
          </option>
        ))}
      </select>
    </div>
  );
}
