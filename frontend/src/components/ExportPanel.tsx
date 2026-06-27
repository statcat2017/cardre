import React, { useState, useMemo } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, formatApiError, getReportServeUrl } from "../api/client";
import { useReportReadiness } from "../hooks/useReportReadiness";
import { BranchSelector } from "./BranchSelector";
import { ReadinessPanel } from "./ReadinessPanel";
import { latestSuccessfulRun } from "../utils/runs";
import type { BranchListItem, GenerateReportResponse } from "../types";
import { theme } from "../styles";

interface Props {
  projectId: string;
  targetBranchId: string | null;
  onBranchSelect?: (branchId: string) => void;
  onStepSelect?: (stepId: string) => void;
}

type ReportMode = "champion" | "branch";

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

export function ExportPanel({ projectId, targetBranchId, onBranchSelect, onStepSelect }: Props) {
  const [reportMode, setReportMode] = useState<ReportMode>("branch");
  const [newReports, setNewReports] = useState<GeneratedReport[]>([]);
  const [lastReport, setLastReport] = useState<GenerateReportResponse | null>(null);
  const [generateErrorMsg, setGenerateErrorMsg] = useState<string>("");

  const { data: projectRuns } = useQuery({
    queryKey: ["projectRuns", projectId],
    queryFn: () => api.getProjectRuns(projectId),
    enabled: !!projectId,
  });
  const latestRun = latestSuccessfulRun(projectRuns?.runs ?? []);

  const { data: branchData } = useQuery({
    queryKey: ["projectBranches", projectId],
    queryFn: () => api.listBranches(projectId, { status: "active" }),
    enabled: !!projectId,
  });
  const branches: BranchListItem[] = branchData?.branches ?? [];

  const {
    data: readinessData,
    isLoading: readinessLoading,
    isFetching: readinessIsFetching,
    error: readinessError,
    refetch: refetchReadiness,
  } = useReportReadiness(
    projectId,
    latestRun?.run_id ?? null,
    targetBranchId,
    reportMode as "branch" | "champion",
  );

  const { data: serverReports } = useQuery<GeneratedReport[]>({
    queryKey: ["reports", projectId, latestRun?.run_id],
    queryFn: () =>
      !latestRun
        ? Promise.resolve([])
        : api.listRunReports(projectId, latestRun.run_id).then((reports) =>
            reports.map((r) => ({
              report_id: r.report_id,
              created_at: r.created_at,
              target_branch_id: r.target_branch_id,
              mode: (r.report_mode || "branch") as ReportMode,
              status: r.status,
              html_path: r.html_path,
              bundle_path: r.bundle_path,
              export_path: r.export_path,
            })),
          ),
    enabled: !!projectId && !!latestRun,
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

  const generateSafetyOk =
    readinessData?.ready === true &&
    !readinessLoading &&
    !readinessIsFetching &&
    !readinessError &&
    latestRun !== null &&
    targetBranchId !== null;

  const generateMutation = useMutation({
    mutationFn: () => {
      if (!generateSafetyOk) throw new Error("Report generation is not ready.");
      if (!latestRun) throw new Error("No run available");
      if (!targetBranchId) throw new Error("No branch selected");
      return api.generateReport(projectId, latestRun.run_id, {
        target_branch_id: targetBranchId ?? "",
        report_mode: reportMode,
        include_supporting_artifacts: true,
        output_formats: ["json", "html"],
      });
    },
    onMutate: () => {
      setGenerateErrorMsg("");
    },
    onSuccess: (data: GenerateReportResponse) => {
      setGenerateErrorMsg("");
      setLastReport(data);
      setNewReports((prev) => [
        {
          report_id: data.report_id,
          created_at: new Date().toISOString(),
          target_branch_id: targetBranchId ?? "",
          mode: reportMode,
          status: data.status,
          html_path: data.html_path,
          bundle_path: data.report_bundle_path,
          export_path: data.export_path,
        },
        ...prev,
      ]);
    },
    onError: (e: unknown) => {
      setGenerateErrorMsg(formatApiError(e));
    },
  });

  const handleOpenReport = (htmlPath: string) => {
    const url = getReportServeUrl(projectId, htmlPath);
    window.open(url, "_blank");
  };

  const selectedBranch = branches.find((b) => b.branch_id === targetBranchId);

  return (
    <div
      style={{
        padding: 24,
        overflowY: "auto",
        flex: 1,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4, color: theme.text }}>
        Audit Pack Export
      </h3>

      {/* Configuration */}
      <div
        style={{
          padding: 16,
          border: `1px solid ${theme.border}`,
          borderRadius: 8,
          backgroundColor: theme.surface,
        }}
      >
        <div style={{ display: "flex", gap: 24, marginBottom: 12, flexWrap: "wrap" }}>
          <div>
            <label
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: theme.textSoft,
                display: "block",
                marginBottom: 4,
              }}
            >
              Report mode
            </label>
            <select
              value={reportMode}
              onChange={(e) => setReportMode(e.target.value as ReportMode)}
              style={{
                padding: "6px 10px",
                borderRadius: 6,
                border: `1px solid ${theme.borderStrong}`,
                fontSize: 13,
                backgroundColor: theme.surface,
                color: theme.text,
              }}
            >
              <option value="champion">Champion report</option>
              <option value="branch">Branch report</option>
            </select>
          </div>

          <BranchSelector
            branches={branches}
            selectedBranchId={targetBranchId}
            onSelect={onBranchSelect}
          />

          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: theme.textSoft, marginBottom: 4 }}>
              Latest run
            </div>
            <div style={{ fontSize: 13, color: theme.muted, paddingTop: 6 }}>
              {latestRun ? (
                <span>
                  <code>{latestRun.run_id.slice(0, 8)}&hellip;</code>
                  {" finished "}
                  {latestRun.finished_at
                    ? new Date(latestRun.finished_at).toLocaleDateString()
                    : "N/A"}
                </span>
              ) : (
                "No successful runs"
              )}
            </div>
          </div>
        </div>

        {/* Generate button */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => generateMutation.mutate()}
            disabled={!generateSafetyOk}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: "none",
              fontSize: 13,
              backgroundColor: generateSafetyOk ? theme.text : theme.mutedSoft,
              color: "#fff",
              cursor: generateSafetyOk ? "pointer" : "not-allowed",
              fontWeight: 600,
            }}
          >
            {generateMutation.isPending ? "Generating..." : "Generate audit pack"}
          </button>
        </div>

        {generateErrorMsg && (
          <div
            role="alert"
            style={{
              padding: 10,
              borderRadius: 6,
              backgroundColor: theme.redBg,
              fontSize: 12,
              color: theme.redText,
              marginTop: 4,
            }}
          >
            Report generation failed: {generateErrorMsg}
          </div>
        )}
      </div>

      {/* Readiness panel with states 1-7 */}
      <ReadinessPanel
        targetBranchId={targetBranchId}
        latestRunId={latestRun?.run_id ?? null}
        branchName={selectedBranch?.name ?? null}
        reportMode={reportMode}
        readinessData={readinessData}
        readinessLoading={readinessLoading}
        readinessIsFetching={readinessIsFetching}
        readinessError={readinessError}
        onStepSelect={onStepSelect}
        onRecheck={() => refetchReadiness()}
      />

      {/* Generated report info */}
      {lastReport && (
        <div
          style={{
            padding: 16,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            backgroundColor: theme.greenBg,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: theme.greenText, marginBottom: 8 }}>
            Report generated
          </div>
          <div style={{ fontSize: 12, color: theme.textSoft, lineHeight: 1.8 }}>
            <div>
              <strong>Bundle:</strong> <code>{lastReport.report_bundle_path}</code>
            </div>
            <div>
              <strong>HTML:</strong> <code>{lastReport.html_path}</code>
            </div>
            <div>
              <strong>Export:</strong> <code>{lastReport.export_path}</code>
            </div>
          </div>
        </div>
      )}

      {/* Generated report history */}
      {mergedReports.length > 0 && (
        <div
          style={{
            padding: 16,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            backgroundColor: theme.surface,
          }}
        >
          <h4 style={{ fontSize: 13, fontWeight: 600, margin: "0 0 8px 0", color: theme.text }}>
            Generated reports
          </h4>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {mergedReports.slice(0, 10).map((r) => (
              <div
                key={r.report_id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "8px 10px",
                  border: `1px solid ${theme.border}`,
                  borderRadius: 6,
                  backgroundColor: theme.surfaceMuted,
                  fontSize: 12,
                  gap: 12,
                }}
              >
                <div style={{ flex: 1 }}>
                  <code style={{ marginRight: 8 }}>{r.report_id.slice(0, 8)}</code>
                  <span style={{ color: theme.muted }}>
                    {new Date(r.created_at).toLocaleString()} &middot; {r.target_branch_id} &middot;{" "}
                    {MODE_LABELS[r.mode]}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  {r.html_path && (
                    <button
                      onClick={() => handleOpenReport(r.html_path)}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 4,
                        border: `1px solid ${theme.border}`,
                        fontSize: 11,
                        backgroundColor: theme.surface,
                        cursor: "pointer",
                        color: theme.text,
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
      {!latestRun && (
        <div
          style={{
            padding: 16,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            backgroundColor: theme.yellowBg,
            fontSize: 12,
            color: theme.yellowText,
          }}
        >
          Run the Scorecard Pathway to completion before exporting. All build, validation, and
          cutoff steps must succeed.
        </div>
      )}
    </div>
  );
}
