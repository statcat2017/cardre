import React, { useState, useReducer, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getReportServeUrl } from "../api/client";
import type {
  BranchListItem,
  RunListItem,
  ReportReadinessItem,
  GenerateReportResponse,
} from "../types";

interface Props {
  projectId: string;
}

type ReportMode = "champion" | "branch";

type UiAction =
  | { type: 'START_CHECK' }
  | { type: 'CHECK_PASSED'; hasWarnings: boolean }
  | { type: 'CHECK_BLOCKED' }
  | { type: 'START_GENERATE' }
  | { type: 'GENERATE_DONE' }
  | { type: 'GENERATE_FAILED' }
  | { type: 'RESET' };

type UiState = { value: "idle" | "checking" | "blocked" | "ready" | "ready_with_warnings" | "generating" | "generated" | "failed" };

function uiReducer(state: UiState, action: UiAction): UiState {
  switch (action.type) {
    case 'START_CHECK': return { value: "checking" };
    case 'CHECK_PASSED': return { value: action.hasWarnings ? "ready_with_warnings" : "ready" };
    case 'CHECK_BLOCKED': return { value: "blocked" };
    case 'START_GENERATE': return { value: "generating" };
    case 'GENERATE_DONE': return { value: "generated" };
    case 'GENERATE_FAILED': return { value: "failed" };
    case 'RESET': return { value: "idle" };
  }
}

interface GeneratedReport {
  report_id: string;
  created_at: string;
  target_branch_id: string;
  mode: ReportMode;
  status: string;
  html_path: string;
  bundle_path: string;
  export_path: string;
}

const MODE_LABELS: Record<ReportMode, string> = {
  champion: "Champion report",
  branch: "Branch report",
};

export function ExportPanel({ projectId }: Props) {
  const queryClient = useQueryClient();
  const [reportMode, setReportMode] = useState<ReportMode>("branch");
  const [targetBranchId, setTargetBranchId] = useState<string>("");
  const [uiState, dispatch] = useReducer(uiReducer, { value: "idle" });
  const [blockers, setBlockers] = useState<ReportReadinessItem[]>([]);
  const [warnings, setWarnings] = useState<ReportReadinessItem[]>([]);
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [newReports, setNewReports] = useState<GeneratedReport[]>([]);
  const [lastReport, setLastReport] = useState<GenerateReportResponse | null>(null);

  const { data: projectRuns } = useQuery({
    queryKey: ["projectRuns", projectId],
    queryFn: () => api.getProjectRuns(projectId),
    enabled: !!projectId,
  });
  const successfulRuns: RunListItem[] = projectRuns?.runs?.filter((r) => r.status === "succeeded") ?? [];
  const latestRun = successfulRuns[0] ?? null;

  const { data: branchData } = useQuery({
    queryKey: ["projectBranches", projectId],
    queryFn: () => api.listBranches(projectId, { status: "active" }),
    enabled: !!projectId,
  });
  const branches: BranchListItem[] = branchData?.branches ?? [];

  const { data: serverReports } = useQuery<GeneratedReport[]>({
    queryKey: ['reports', projectId],
    queryFn: () => Promise.resolve([]),
    enabled: !!projectId,
  });

  const mergedReports = useMemo(() => {
    const serverList = serverReports ?? [];
    const seen = new Set<string>();
    const merged: GeneratedReport[] = [];
    for (const r of [...newReports, ...serverList]) {
      if (!seen.has(r.report_id)) {
        seen.add(r.report_id);
        merged.push(r);
      }
    }
    return merged;
  }, [newReports, serverReports]);

  React.useEffect(() => {
    if (!targetBranchId && branches.length > 0) {
      setTargetBranchId(branches[0].branch_id);
    }
  }, [branches, targetBranchId]);

  useEffect(() => {
    dispatch({ type: 'RESET' });
    setBlockers([]);
    setWarnings([]);
    setErrorMsg("");
  }, [targetBranchId, reportMode]);

  const checkReadinessMutation = useMutation({
    mutationFn: () => {
      if (!latestRun) throw new Error("No run available");
      return api.getReportReadiness(projectId, latestRun.run_id, {
        target_branch_id: targetBranchId,
        report_mode: reportMode,
      });
    },
    onMutate: () => {
      dispatch({ type: 'START_CHECK' });
      setBlockers([]);
      setWarnings([]);
      setErrorMsg("");
    },
    onSuccess: (data) => {
      setBlockers(data.blockers ?? []);
      setWarnings(data.warnings ?? []);
      if (!data.ready) {
        dispatch({ type: 'CHECK_BLOCKED' });
      } else {
        dispatch({ type: 'CHECK_PASSED', hasWarnings: (data.warnings ?? []).length > 0 });
      }
    },
    onError: (e: any) => {
      dispatch({ type: 'GENERATE_FAILED' });
      setErrorMsg(e.detail?.message || e.message || "Readiness check failed");
    },
  });

  const generateMutation = useMutation({
    mutationFn: () => {
      if (!latestRun) throw new Error("No run available");
      return api.generateReport(projectId, latestRun.run_id, {
        target_branch_id: targetBranchId,
        report_mode: reportMode,
        include_supporting_artifacts: true,
        output_formats: ["json", "html"],
      });
    },
    onMutate: () => {
      dispatch({ type: 'START_GENERATE' });
      setErrorMsg("");
    },
    onSuccess: (data) => {
      dispatch({ type: 'GENERATE_DONE' });
      setLastReport(data);
      setNewReports((prev) => [
        {
          report_id: data.report_id,
          created_at: new Date().toISOString(),
          target_branch_id: targetBranchId,
          mode: reportMode,
          status: data.status,
          html_path: data.html_path,
          bundle_path: data.report_bundle_path,
          export_path: data.export_path,
        },
        ...prev,
      ]);
    },
    onError: (e: any) => {
      dispatch({ type: 'GENERATE_FAILED' });
      setErrorMsg(e.detail?.message || e.message || "Report generation failed");
    },
  });

  const handleOpenReport = (htmlPath: string) => {
    const url = getReportServeUrl(projectId, htmlPath);
    window.open(url, "_blank");
  };

  const branchOptions = branches.filter((b) => b.status === "active");
  const selectedBranch = branchOptions.find((b) => b.branch_id === targetBranchId);

  return (
    <div style={{ padding: 16, overflowY: "auto", flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Audit Pack Export</h3>

      {/* Configuration */}
      <div style={{ padding: 16, border: "1px solid #e2e8f0", borderRadius: 8, backgroundColor: "#fff" }}>
        <div style={{ display: "flex", gap: 24, marginBottom: 12, flexWrap: "wrap" }}>
          {/* Report mode */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#475569", display: "block", marginBottom: 4 }}>
              Report mode
            </label>
            <select
              value={reportMode}
              onChange={(e) => setReportMode(e.target.value as ReportMode)}
              style={{
                padding: "6px 10px", borderRadius: 6, border: "1px solid #cbd5e1",
                fontSize: 13, backgroundColor: "#fff",
              }}
            >
              <option value="champion">Champion report</option>
              <option value="branch">Branch report</option>
            </select>
          </div>

          {/* Target branch */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#475569", display: "block", marginBottom: 4 }}>
              Target branch
            </label>
            <select
              value={targetBranchId}
              onChange={(e) => setTargetBranchId(e.target.value)}
              style={{
                padding: "6px 10px", borderRadius: 6, border: "1px solid #cbd5e1",
                fontSize: 13, backgroundColor: "#fff",
              }}
            >
              {branchOptions.length === 0 && <option value="">No branches available</option>}
              {branchOptions.map((b) => (
                <option key={b.branch_id} value={b.branch_id}>
                  {b.name || b.branch_id} {b.is_champion ? "(champion)" : ""}
                </option>
              ))}
            </select>
          </div>

          {/* Latest run */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#475569", marginBottom: 4 }}>Latest run</div>
            <div style={{ fontSize: 13, color: "#64748b", paddingTop: 6 }}>
              {latestRun ? (
                <span>
                  <code>{latestRun.run_id.slice(0, 8)}&hellip;</code>
                  {" finished "}
                  {latestRun.finished_at ? new Date(latestRun.finished_at).toLocaleDateString() : "N/A"}
                </span>
              ) : (
                "No successful runs"
              )}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => checkReadinessMutation.mutate()}
            disabled={checkReadinessMutation.isPending || !latestRun || !targetBranchId}
            style={{
              padding: "8px 16px", borderRadius: 6, border: "1px solid #cbd5e1",
              fontSize: 13, backgroundColor: "#f8fafc", cursor: "pointer",
              fontWeight: 500, color: "#334155",
              opacity: checkReadinessMutation.isPending || !latestRun || !targetBranchId ? 0.5 : 1,
            }}
          >
            {checkReadinessMutation.isPending ? "Checking..." : "Check readiness"}
          </button>

          <button
            onClick={() => generateMutation.mutate()}
            disabled={uiState.value !== "ready" && uiState.value !== "ready_with_warnings"}
            style={{
              padding: "8px 16px", borderRadius: 6, border: "none",
              fontSize: 13, backgroundColor: uiState.value === "ready" || uiState.value === "ready_with_warnings" ? "#0369a1" : "#94a3b8",
              color: "#fff", cursor: uiState.value === "ready" || uiState.value === "ready_with_warnings" ? "pointer" : "not-allowed",
              fontWeight: 600,
            }}
          >
            {generateMutation.isPending ? "Generating..." : "Generate audit pack"}
          </button>
        </div>
      </div>

      {/* Readiness display */}
      {(uiState.value === "blocked" || uiState.value === "ready" || uiState.value === "ready_with_warnings") && (
        <div
          style={{
            padding: 16, border: "1px solid #e2e8f0", borderRadius: 8,
            backgroundColor: uiState.value === "blocked" ? "#fef2f2" : "#f8fafc",
          }}
        >
          {blockers.map((b) => (
            <div key={b.code} style={{ padding: "4px 0", fontSize: 13, color: "#dc2626" }}>
              <strong style={{ marginRight: 8 }}>&#10060;</strong>
              <strong>{b.code}:</strong> {b.message}
            </div>
          ))}
          {warnings.map((w) => (
            <div key={w.code} style={{ padding: "4px 0", fontSize: 13, color: "#92400e" }}>
              <strong style={{ marginRight: 8 }}>&#9888;</strong>
              <strong>{w.code}:</strong> {w.message}
            </div>
          ))}
          {blockers.length === 0 && warnings.length === 0 && (
            <div style={{ fontSize: 13, color: "#166534" }}>
              <strong>&#10003;</strong> All evidence available. Ready to generate.
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {uiState.value === "failed" && errorMsg && (
        <div style={{ padding: 12, border: "1px solid #fca5a5", borderRadius: 8, backgroundColor: "#fef2f2", fontSize: 13, color: "#dc2626" }}>
          <strong>Error:</strong> {errorMsg}
        </div>
      )}

      {/* Generated report info */}
      {lastReport && (
        <div style={{ padding: 16, border: "1px solid #bbf7d0", borderRadius: 8, backgroundColor: "#f0fdf4" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#166534", marginBottom: 8 }}>
            &#10003; Report generated
          </div>
          <div style={{ fontSize: 12, color: "#475569", lineHeight: 1.8 }}>
            <div><strong>Bundle:</strong> <code>{lastReport.report_bundle_path}</code></div>
            <div><strong>HTML:</strong> <code>{lastReport.html_path}</code></div>
            <div><strong>Export:</strong> <code>{lastReport.export_path}</code></div>
          </div>
        </div>
      )}

      {/* Generated report history */}
      {mergedReports.length > 0 && (
        <div style={{ padding: 16, border: "1px solid #e2e8f0", borderRadius: 8, backgroundColor: "#fff" }}>
          <h4 style={{ fontSize: 13, fontWeight: 600, margin: "0 0 8px 0" }}>Generated reports</h4>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {mergedReports.slice(0, 10).map((r) => (
              <div
                key={r.report_id}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "8px 10px", border: "1px solid #e2e8f0", borderRadius: 6,
                  backgroundColor: "#f8fafc", fontSize: 12, gap: 12,
                }}
              >
                <div style={{ flex: 1 }}>
                  <code style={{ marginRight: 8 }}>{r.report_id.slice(0, 8)}</code>
                  <span style={{ color: "#64748b" }}>
                    {new Date(r.created_at).toLocaleString()} &middot; {r.target_branch_id} &middot; {MODE_LABELS[r.mode]}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  {r.html_path && (
                    <button
                      onClick={() => handleOpenReport(r.html_path)}
                      style={{
                        padding: "4px 10px", borderRadius: 4, border: "1px solid #cbd5e1",
                        fontSize: 11, backgroundColor: "#fff", cursor: "pointer",
                      }}
                    >
                      Open report
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Fallback when no runs */}
      {successfulRuns.length === 0 && (
        <div style={{ padding: 16, border: "1px solid #fde68a", borderRadius: 8, backgroundColor: "#fffbeb", fontSize: 12, color: "#92400e" }}>
          Run the Scorecard Pathway to completion before exporting. All build, validation, and cutoff steps must succeed.
        </div>
      )}
    </div>
  );
}
