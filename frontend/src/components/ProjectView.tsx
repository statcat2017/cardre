import React, { useState, useCallback, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { StepCardGrid } from "./StepCardGrid";
import { ArtifactList } from "./ArtifactList";
import { ProfileOutput } from "./ProfileOutput";
import type { PlanResponse, RunStepsResponse, StepStatus } from "../types";

interface Props {
  projectId: string;
  onBack: () => void;
}

export function ProjectView({ projectId, onBack }: Props) {
  const [running, setRunning] = useState(false);
  const [planId, setPlanId] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    refetchInterval: 5000,
  });

  // Look up plan_id from project details
  useEffect(() => {
    if (!project) return;
    const lookupPlan = async () => {
      const base = (window as any).__API_URL__ || "http://127.0.0.1:8752";
      const planResp = await fetch(`${base}/plans`).catch(() => null);
      if (!planResp) return;
      const plans = await planResp.json().catch(() => null);
    };
    lookupPlan();
  }, [project]);

  const [importPath, setImportPath] = useState("");

  // Fetch the plan from the API once we have planId
  const { data: planData, refetch: refetchPlan } = useQuery({
    queryKey: ["plan", planId],
    queryFn: () => api.getPlan(planId!),
    enabled: !!planId,
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (planData) setPlan(planData);
  }, [planData]);

  // Fetch artifacts
  const { data: allArtifacts } = useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: async () => {
      const base = (window as any).__API_URL__ || "http://127.0.0.1:8752";
      const resp = await fetch(`${base}/artifacts`).catch(() => null);
      if (!resp) return [];
      const list = await resp.json().catch(() => []);
      return Array.isArray(list) ? list : [];
    },
    enabled: !!projectId,
    refetchInterval: 10000,
  });

  const artifacts = Array.isArray(allArtifacts) ? allArtifacts : [];

  // Handle import
  const handleImport = async () => {
    if (!importPath.trim()) return;
    setError(null);
    try {
      await api.importDataset({
        project_id: projectId,
        source_path: importPath.trim(),
        dataset_id: "uci-statlog-german-credit",
      });
      // After import, find and load the plan
      const projDetail = await api.getProject(projectId);
      if (projDetail.plan_count > 0) {
        const base = (window as any).__API_URL__ || "http://127.0.0.1:8752";
        const planResp = await fetch(`${base}/plans`).then((r) => r.json()).catch(() => null);
        if (planResp && planResp.length > 0) {
          setPlanId(planResp[0].plan_id);
        }
      }
    } catch (e: any) {
      setError(e.message);
    }
  };

  // Handle run
  const handleRun = async () => {
    if (!planId || !plan) return;
    setRunning(true);
    setError(null);
    try {
      await api.runPlan({
        project_id: projectId,
        plan_version_id: plan.latest_version_id,
      });
      await refetchPlan();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  if (projectLoading) {
    return <div style={{ padding: 24 }}>Loading project...</div>;
  }

  if (!project) {
    return <div style={{ padding: 24 }}>Project not found.</div>;
  }

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: "0 auto" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 24,
        }}
      >
        <div>
          <button
            onClick={onBack}
            style={{
              background: "none",
              border: "none",
              color: "#3b82f6",
              cursor: "pointer",
              fontSize: 14,
              padding: 0,
              marginBottom: 4,
            }}
          >
            &larr; Back
          </button>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>{project.name}</h1>
          <div style={{ fontSize: 12, color: "#6b7280" }}>{project.path}</div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
            Plans: {project.plan_count} | Runs: {project.run_count}
          </div>
        </div>
        <button
          onClick={handleRun}
          disabled={running || !plan}
          style={{
            padding: "10px 24px",
            borderRadius: 6,
            border: "none",
            backgroundColor: running ? "#93c5fd" : plan ? "#22c55e" : "#d1d5db",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: running || !plan ? "not-allowed" : "pointer",
          }}
        >
          {running ? "Running..." : plan ? "Run Pathway" : "Import First"}
        </button>
      </div>

      {error && (
        <div
          style={{
            padding: "8px 12px",
            backgroundColor: "#fef2f2",
            color: "#dc2626",
            borderRadius: 6,
            marginBottom: 16,
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {/* Import section */}
      {(!plan || plan.steps.every((s) => s.status === "not_run")) && (
        <div
          style={{
            padding: 16,
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            marginBottom: 24,
            backgroundColor: "#f9fafb",
          }}
        >
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
            Import Dataset
          </h3>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              placeholder="/path/to/german.data"
              style={{
                flex: 1,
                padding: "8px 12px",
                border: "1px solid #d1d5db",
                borderRadius: 6,
                fontSize: 14,
              }}
            />
            <button
              onClick={handleImport}
              style={{
                padding: "8px 16px",
                borderRadius: 6,
                border: "none",
                backgroundColor: "#3b82f6",
                color: "#fff",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Import
            </button>
          </div>
        </div>
      )}

      {/* Plan / Step cards */}
      {plan && (
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
            {plan.name}
            <span style={{ fontSize: 13, color: "#6b7280", marginLeft: 8 }}>
              ({plan.steps.filter((s) => s.status === "succeeded").length}/{plan.steps.length} succeeded)
            </span>
          </h2>
          <StepCardGrid steps={plan.steps} />
        </div>
      )}

      {!plan && project.plan_count > 0 && (
        <div style={{ marginBottom: 24 }}>
          <button
            onClick={async () => {
              try {
                const projDetail = await api.getProject(projectId);
                const base = (window as any).__API_URL__ || "http://127.0.0.1:8752";
                const planResp = await fetch(`${base}/plans`).then((r) => r.json()).catch(() => null);
                if (planResp && planResp.length > 0) {
                  setPlanId(planResp[0].plan_id);
                }
              } catch {}
            }}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: "1px solid #d1d5db",
              backgroundColor: "#fff",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            Load Plan
          </button>
        </div>
      )}

      {/* Artifacts */}
      <div style={{ marginTop: 16 }}>
        <ArtifactList
          artifacts={artifacts as any[]}
          loading={false}
        />
      </div>
    </div>
  );
}
