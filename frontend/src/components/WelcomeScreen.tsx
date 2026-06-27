import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { ImportDatasetForm } from "./ImportDatasetForm";
import { theme } from "../styles";

interface Props {
  onProjectCreated: (projectId: string) => void;
}

export function WelcomeScreen({ onProjectCreated }: Props) {
  const [projectPath, setProjectPath] = useState("");
  const [projectName, setProjectName] = useState("My Scorecard");
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
        padding: 32,
        backgroundColor: theme.canvas,
      }}
    >
      <div style={{ maxWidth: 560, width: "100%" }}>
        <div
          style={{
            margin: "0 auto 18px",
            width: 48,
            height: 28,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            backgroundColor: theme.surface,
          }}
        />
        <h1
          style={{
            fontFamily: theme.fontSerif,
            fontSize: 44,
            fontWeight: 600,
            letterSpacing: "-0.04em",
            lineHeight: 1.05,
            marginBottom: 8,
            textAlign: "center",
            color: theme.text,
          }}
        >
          Cardre
        </h1>
        <p style={{ textAlign: "center", color: theme.muted, marginBottom: 40, fontSize: 15 }}>
          A quiet workspace for auditable credit scorecard modelling.
        </p>

        {error && (
          <div
            style={{
              padding: "10px 12px",
              backgroundColor: theme.redBg,
              color: theme.redText,
              border: `1px solid ${theme.border}`,
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
              padding: 32,
              border: `1px solid ${theme.border}`,
              borderRadius: 12,
              backgroundColor: theme.surface,
            }}
          >
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 18, color: theme.text }}>
              Create Project
            </h2>
            <div style={{ marginBottom: 12 }}>
              <label
                style={{
                  display: "block",
                  fontSize: 12,
                  fontWeight: 600,
                  marginBottom: 4,
                  color: theme.textSoft,
                }}
              >
                Project Path
              </label>
              <input
                type="text"
                value={projectPath}
                onChange={(e) => setProjectPath(e.target.value)}
                placeholder="/home/user/my-scorecard.cardre"
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  border: `1px solid ${theme.borderStrong}`,
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: "border-box",
                  color: theme.text,
                  backgroundColor: theme.surface,
                }}
              />
              <div style={{ fontSize: 11, color: theme.muted, marginTop: 4 }}>
                Directory path ending in .cardre (e.g. ~/my-project.cardre)
              </div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <label
                style={{
                  display: "block",
                  fontSize: 12,
                  fontWeight: 600,
                  marginBottom: 4,
                  color: theme.textSoft,
                }}
              >
                Project Name
              </label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="My Scorecard"
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  border: `1px solid ${theme.borderStrong}`,
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: "border-box",
                  color: theme.text,
                  backgroundColor: theme.surface,
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
                backgroundColor: createMutation.isPending ? theme.mutedSoft : theme.text,
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

        {step === "import" && projectId && (
          <ImportDatasetForm
            projectId={projectId}
            onImported={() => {
              setStep("ready");
              setError(null);
            }}
            onError={(e) => setError(e.message)}
            label="File Path"
            headerContent={
              <div
                style={{
                  padding: "12px 14px",
                  backgroundColor: theme.blueBg,
                  border: `1px solid ${theme.border}`,
                  borderRadius: 6,
                  fontSize: 12,
                  color: theme.blueText,
                  marginBottom: 16,
                  lineHeight: 1.5,
                }}
              >
                <strong>How it works:</strong> Import runs in a hidden <code>__import__</code> plan
                to preserve source-data evidence separately. After import, the{" "}
                <strong>Scorecard Pathway</strong> consumes the imported artifact and records its
                own modelling run evidence — the two plans remain independent so you can always
                trace the original source data. Import evidence is visible in the Artifacts browser.
              </div>
            }
          />
        )}

        {step === "ready" && (
          <div
            style={{
              padding: 32,
              border: `1px solid ${theme.border}`,
              borderRadius: 12,
              textAlign: "center",
              backgroundColor: theme.surface,
            }}
          >
            <div
              style={{
                display: "inline-flex",
                padding: "2px 8px",
                borderRadius: 9999,
                backgroundColor: theme.greenBg,
                color: theme.greenText,
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                marginBottom: 10,
              }}
            >
              Ready
            </div>
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8, color: theme.text }}>
              Ready to Go
            </h2>
            <p style={{ color: theme.muted, fontSize: 13, marginBottom: 16 }}>
              Dataset imported and proof pathway registered.
            </p>
            <button
              onClick={handleOpenProject}
              style={{
                padding: "10px 24px",
                borderRadius: 6,
                border: "none",
                backgroundColor: theme.text,
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
