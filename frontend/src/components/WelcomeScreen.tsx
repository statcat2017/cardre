import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  onProjectCreated: (projectId: string) => void;
}

export function WelcomeScreen({ onProjectCreated }: Props) {
  const [projectPath, setProjectPath] = useState("");
  const [projectName, setProjectName] = useState("My Scorecard");
  const [importPath, setImportPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<"create" | "import" | "ready">("create");
  const [projectId, setProjectId] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (body: { path: string; name: string }) => api.createProject(body),
    onSuccess: (data) => {
      setProjectId(data.project_id);
      setStep("import");
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const importMutation = useMutation({
    mutationFn: (body: { project_id: string; source_path: string }) =>
      api.importDataset({
        ...body,
        dataset_id: "",
        format: "auto",
        has_header: true,
        schema_overrides: {},
      }),
    onSuccess: () => {
      setStep("ready");
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const handleCreate = () => {
    if (!projectPath.trim()) {
      setError("Please enter a project path");
      return;
    }
    if (!projectName.trim()) {
      setError("Please enter a project name");
      return;
    }
    createMutation.mutate({ path: projectPath.trim(), name: projectName.trim() });
  };

  const handleImport = () => {
    if (!importPath.trim()) {
      setError("Please enter the path to a data file (CSV, TSV, or Parquet)");
      return;
    }
    if (!projectId) return;
    importMutation.mutate({
      project_id: projectId,
      source_path: importPath.trim(),
    });
  };

  const handleOpenProject = () => {
    if (!projectId) return;
    onProjectCreated(projectId);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        padding: 24,
      }}
    >
      <div style={{ maxWidth: 480, width: "100%" }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8, textAlign: "center" }}>
          Cardre
        </h1>
        <p style={{ textAlign: "center", color: "#6b7280", marginBottom: 32 }}>
          Auditable credit scorecard builder
        </p>

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

        {step === "create" && (
          <div
            style={{
              padding: 24,
              border: "1px solid #e5e7eb",
              borderRadius: 8,
            }}
          >
            <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>
              Create Project
            </h2>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                Project Path
              </label>
              <input
                type="text"
                value={projectPath}
                onChange={(e) => setProjectPath(e.target.value)}
                placeholder="/home/user/my-scorecard.cardre"
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  border: "1px solid #d1d5db",
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: "border-box",
                }}
              />
              <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>
                Directory path ending in .cardre (e.g. ~/my-project.cardre)
              </div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                Project Name
              </label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="My Scorecard"
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  border: "1px solid #d1d5db",
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: "border-box",
                }}
              />
            </div>
            <button
              onClick={handleCreate}
              disabled={createMutation.isPending}
              style={{
                width: "100%",
                padding: "10px 16px",
                borderRadius: 6,
                border: "none",
                backgroundColor: createMutation.isPending ? "#93c5fd" : "#3b82f6",
                color: "#fff",
                fontSize: 14,
                fontWeight: 600,
                cursor: createMutation.isPending ? "not-allowed" : "pointer",
              }}
            >
              {createMutation.isPending ? "Creating..." : "Create Project"}
            </button>
          </div>
        )}

        {step === "import" && (
          <div
            style={{
              padding: 24,
              border: "1px solid #e5e7eb",
              borderRadius: 8,
            }}
          >
            <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>
              Import Dataset
            </h2>
            <div
              style={{
                padding: "8px 12px",
                backgroundColor: "#f0f9ff",
                border: "1px solid #bae6fd",
                borderRadius: 6,
                fontSize: 12,
                color: "#0369a1",
                marginBottom: 16,
                lineHeight: 1.5,
              }}
            >
              <strong>How it works:</strong> Import runs in a hidden <code>__import__</code>{' '}
              plan to preserve source-data evidence separately. After import, the{' '}
              <strong>Scorecard Pathway</strong> consumes the imported artifact and records
              its own modelling run evidence — the two plans remain independent
              so you can always trace the original source data. Import evidence is
              visible in the Artifacts browser.
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                File Path
              </label>
              <input
                type="text"
                value={importPath}
                onChange={(e) => setImportPath(e.target.value)}
                placeholder="/path/to/applications.csv"
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  border: "1px solid #d1d5db",
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: "border-box",
                }}
              />
            </div>
            <button
              onClick={handleImport}
              disabled={importMutation.isPending}
              style={{
                width: "100%",
                padding: "10px 16px",
                borderRadius: 6,
                border: "none",
                backgroundColor: importMutation.isPending ? "#93c5fd" : "#3b82f6",
                color: "#fff",
                fontSize: 14,
                fontWeight: 600,
                cursor: importMutation.isPending ? "not-allowed" : "pointer",
              }}
            >
              {importMutation.isPending ? "Importing..." : "Import"}
            </button>
          </div>
        )}

        {step === "ready" && (
          <div
            style={{
              padding: 24,
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 24, marginBottom: 8 }}>&#10003;</div>
            <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
              Ready to Go
            </h2>
            <p style={{ color: "#6b7280", fontSize: 13, marginBottom: 16 }}>
              Dataset imported and proof pathway registered.
            </p>
            <button
              onClick={handleOpenProject}
              style={{
                padding: "10px 24px",
                borderRadius: 6,
                border: "none",
                backgroundColor: "#22c55e",
                color: "#fff",
                fontSize: 14,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Open Project
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
