import React, { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { TopBar } from "./TopBar";
import { LeftNav } from "./LeftNav";
import { PathwayView } from "./PathwayView";
import { StepInspector } from "./StepInspector";
import { BottomDrawer } from "./BottomDrawer";
import { DatasetImport } from "./DatasetImport";
import { RunHistoryPanel } from "./RunHistoryPanel";
import { ArtifactBrowser } from "./ArtifactBrowser";
import { ManualBinningEditor } from "./ManualBinningEditor";
import { ExportPanel } from "./ExportPanel";
import type { PlanResponse, StepStatus, UpdateStepParamsResponse } from "../types";

interface Props {
  projectId: string;
  onBack: () => void;
}

export function ProjectView({ projectId, onBack }: Props) {
  const queryClient = useQueryClient();
  const [running, setRunning] = useState(false);
  const [activeSection, setActiveSection] = useState("pathway");
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<string[]>([]);

  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
  });

  const { data: projectPlans } = useQuery({
    queryKey: ["projectPlans", projectId],
    queryFn: () => api.getProjectPlans(projectId),
    enabled: !!projectId,
  });

  // Find the default scorecard plan
  const scorecardPlan = projectPlans?.plans?.find((p) => p.is_default);

  const { data: planData, refetch: refetchPlan } = useQuery({
    queryKey: ["plan", scorecardPlan?.plan_id],
    queryFn: () => api.getPlan(scorecardPlan!.plan_id, projectId),
    enabled: !!scorecardPlan?.plan_id,
  });

  const handlePlanRefreshed = useCallback(
    (detailOrResp: UpdateStepParamsResponse | { latest_version_id?: string }) => {
      refetchPlan();
      if ("latest_version_id" in detailOrResp && detailOrResp.latest_version_id) {
        setDiagnostics((prev) => [
          ...prev,
          `[${new Date().toLocaleTimeString()}] Plan refreshed to version ${(detailOrResp.latest_version_id as string).slice(0, 8)}…`,
        ]);
      } else if ("new_plan_version_id" in detailOrResp) {
        setDiagnostics((prev) => [
          ...prev,
          `[${new Date().toLocaleTimeString()}] New plan version created: ${detailOrResp.new_plan_version_id.slice(0, 8)}…`,
        ]);
      }
    },
    [refetchPlan],
  );

  // After import, re-fetch project plans
  const handleImported = () => {
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["projectPlans", projectId] });
    setDiagnostics((prev) => [
      ...prev,
      `[${new Date().toLocaleTimeString()}] Dataset imported — pathway import step configured`,
    ]);
  };

  const handleRun = async () => {
    if (!scorecardPlan || !planData) return;
    setRunning(true);
    setError(null);
    setDiagnostics((prev) => [...prev, `[${new Date().toLocaleTimeString()}] Starting pathway run...`]);
    try {
      await api.runPlan({
        project_id: projectId,
        plan_version_id: planData.latest_version_id,
      });
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projectRuns", projectId] });
      await refetchPlan();
      setDiagnostics((prev) => [...prev, `[${new Date().toLocaleTimeString()}] Run completed`]);
    } catch (e: any) {
      setError(e.message);
      setDiagnostics((prev) => [...prev, `[${new Date().toLocaleTimeString()}] Run failed: ${e.message}`]);
    } finally {
      setRunning(false);
    }
  };

  const handleStepSelect = (stepId: string) => {
    if (selectedStepId === stepId) {
      setSelectedStepId(null);
    } else {
      setSelectedStepId(stepId);
      setEditingStepId(null);
    }
  };

  const handleEditManualBinning = () => {
    setEditingStepId("manual-binning");
    setActiveSection("pathway"); // Keep pathway visible in nav
  };

  const handleBackFromEdit = () => {
    setEditingStepId(null);
  };

  const selectedStep: StepStatus | null =
    planData?.steps?.find((s: StepStatus) => s.step_id === selectedStepId) ?? null;

  const planName = planData?.name ?? null;
  const basePlanVersionId = planData?.latest_version_id ?? null;
  const planId = scorecardPlan?.plan_id ?? null;

  if (projectLoading) {
    return <div style={{ padding: 24 }}>Loading project...</div>;
  }

  if (!project) {
    return <div style={{ padding: 24 }}>Project not found.</div>;
  }

  const diagnosticsMessages = [
    ...diagnostics,
    error ? `[error] ${error}` : null,
  ].filter(Boolean) as string[];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <TopBar
        project={project}
        planName={planName}
        running={running}
        onRun={handleRun}
        canRun={!!scorecardPlan && !running}
      />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <LeftNav activeSection={activeSection} onSectionChange={setActiveSection} />

        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {/* Manual Binning Editor takes over center when editing */}
          {editingStepId === "manual-binning" && planId && basePlanVersionId && (
            <ManualBinningEditor
              planId={planId}
              projectId={projectId}
              basePlanVersionId={basePlanVersionId}
              onBack={handleBackFromEdit}
              onPlanRefreshed={handlePlanRefreshed}
            />
          )}

          {/* Pathway View */}
          {activeSection === "pathway" && !editingStepId && planData && (
            <PathwayView
              steps={planData.steps}
              selectedStepId={selectedStepId}
              onStepSelect={handleStepSelect}
            />
          )}

          {activeSection === "pathway" && !editingStepId && !planData && (
            <div style={{ padding: 24, color: "#64748b" }}>
              No scorecard pathway found. Create a project to get started.
            </div>
          )}

          {activeSection === "dataset" && (
            <DatasetImport projectId={projectId} onImported={handleImported} />
          )}

          {activeSection === "runs" && <RunHistoryPanel projectId={projectId} />}

          {activeSection === "artifacts" && <ArtifactBrowser projectId={projectId} />}

          {activeSection === "exports" && <ExportPanel projectId={projectId} />}

          {activeSection === "diagnostics" && (
            <div style={{ padding: 16, overflowY: "auto", flex: 1 }}>
              <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Diagnostics</h3>
              {diagnosticsMessages.length === 0 ? (
                <div style={{ color: "#64748b", fontSize: 13 }}>No diagnostics yet.</div>
              ) : (
                diagnosticsMessages.map((msg, i) => (
                  <div
                    key={i}
                    style={{
                      fontFamily: "monospace",
                      fontSize: 12,
                      lineHeight: 1.8,
                      padding: "4px 0",
                      borderBottom: "1px solid #f1f5f9",
                      color: msg.startsWith("[error]") ? "#dc2626" : "#475569",
                    }}
                  >
                    {msg}
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        <StepInspector
          step={selectedStep}
          planId={planId}
          projectId={projectId}
          basePlanVersionId={basePlanVersionId}
          currentParams={selectedStep?.params ?? {}}
          onPlanRefreshed={handlePlanRefreshed}
          onEditManualBinning={handleEditManualBinning}
        />
      </div>

      <BottomDrawer messages={diagnosticsMessages} />
    </div>
  );
}
