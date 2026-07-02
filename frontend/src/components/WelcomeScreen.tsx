import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import { theme, pageCardStyle } from "../styles";

interface Props {
  onProjectCreated: (projectId: string, projectPath: string) => void;
}

export function WelcomeScreen({ onProjectCreated }: Props) {
  const [projectPath, setProjectPath] = useState(
    () => window.localStorage.getItem("cardre.projectPath") ?? "",
  );
  const [projectName, setProjectName] = useState("My Scorecard");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (projectPath.trim()) {
      window.localStorage.setItem("cardre.projectPath", projectPath.trim());
    }
  }, [projectPath]);

  const projectsQuery = useQuery({
    queryKey: ["projects", projectPath],
    queryFn: () => api.listProjects({ projectPath: projectPath.trim() }),
    enabled: projectPath.trim().length > 0,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.createProject(
        { projectPath: projectPath.trim() },
        { name: projectName.trim(), path: projectPath.trim() },
      ),
    onSuccess: (project) => {
      setError(null);
      onProjectCreated(project.project_id, projectPath.trim());
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.detail : err instanceof Error ? err.message : String(err),
      );
    },
  });

  return (
    <main
      style={{
        minHeight: "100vh",
        padding: "32px 20px",
        background: theme.canvas,
        color: theme.text,
        fontFamily: theme.fontSans,
      }}
    >
      <div style={{ maxWidth: 1080, margin: "0 auto", display: "grid", gap: 20 }}>
        <section style={{ ...pageCardStyle, padding: 28 }}>
          <p
            style={{
              margin: 0,
              fontSize: 12,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: theme.muted,
            }}
          >
            Cardre
          </p>
          <h1
            style={{
              margin: "10px 0 8px",
              fontFamily: theme.fontSerif,
              fontSize: "clamp(2.4rem, 6vw, 4.6rem)",
              lineHeight: 1.02,
            }}
          >
            Evidence-first scorecard workflows.
          </h1>
          <p
            style={{
              margin: 0,
              maxWidth: 720,
              fontSize: 15,
              lineHeight: 1.7,
              color: theme.textSoft,
            }}
          >
            Open a local project root, create a project, then inspect plans, versions, and run
            history.
          </p>
        </section>

        <section
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
            gap: 20,
          }}
        >
          <form
            style={{ ...pageCardStyle, padding: 24 }}
            onSubmit={(event) => {
              event.preventDefault();
              setError(null);
              if (!projectPath.trim()) {
                setError("Enter a project root path.");
                return;
              }
              if (!projectName.trim()) {
                setError("Enter a project name.");
                return;
              }
              createMutation.mutate();
            }}
          >
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Create Project</h2>
            <label
              style={{
                display: "block",
                fontSize: 12,
                fontWeight: 600,
                color: theme.muted,
                marginBottom: 10,
              }}
            >
              Project root
              <input
                value={projectPath}
                onChange={(event) => setProjectPath(event.target.value)}
                placeholder="/home/me/example.cardre"
                style={{
                  display: "block",
                  width: "100%",
                  marginTop: 6,
                  padding: "10px 12px",
                  border: `1px solid ${theme.borderStrong}`,
                  borderRadius: 10,
                  background: theme.surface,
                  boxSizing: "border-box",
                }}
              />
            </label>
            <label
              style={{
                display: "block",
                fontSize: 12,
                fontWeight: 600,
                color: theme.muted,
                marginBottom: 14,
              }}
            >
              Project name
              <input
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                placeholder="My Scorecard"
                style={{
                  display: "block",
                  width: "100%",
                  marginTop: 6,
                  padding: "10px 12px",
                  border: `1px solid ${theme.borderStrong}`,
                  borderRadius: 10,
                  background: theme.surface,
                  boxSizing: "border-box",
                }}
              />
            </label>
            {error && (
              <div
                style={{
                  marginBottom: 12,
                  padding: 12,
                  borderRadius: 10,
                  background: theme.redBg,
                  color: theme.redText,
                  fontSize: 13,
                }}
              >
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={createMutation.isPending}
              style={{
                width: "100%",
                padding: "11px 14px",
                border: 0,
                borderRadius: 10,
                background: createMutation.isPending ? theme.mutedSoft : theme.text,
                color: "#fff",
                fontWeight: 600,
                cursor: createMutation.isPending ? "not-allowed" : "pointer",
              }}
            >
              {createMutation.isPending ? "Creating..." : "Create Project"}
            </button>
          </form>

          <section style={{ ...pageCardStyle, padding: 24 }}>
            <h2 style={{ marginTop: 0, fontSize: 18 }}>Existing Projects</h2>
            {!projectPath.trim() ? (
              <p style={{ margin: 0, color: theme.muted, fontSize: 14 }}>
                Enter a project root to load projects in that store.
              </p>
            ) : projectsQuery.isLoading ? (
              <p style={{ margin: 0, color: theme.muted, fontSize: 14 }}>Loading projects...</p>
            ) : projectsQuery.data?.projects.length ? (
              <div style={{ display: "grid", gap: 10 }}>
                {projectsQuery.data.projects.map((project) => (
                  <button
                    key={project.project_id}
                    type="button"
                    onClick={() => onProjectCreated(project.project_id, projectPath.trim())}
                    style={{
                      textAlign: "left",
                      border: `1px solid ${theme.border}`,
                      borderRadius: 12,
                      padding: 14,
                      background: theme.canvasSoft,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>{project.name}</div>
                    <div style={{ fontSize: 12, color: theme.muted }}>{project.project_id}</div>
                  </button>
                ))}
              </div>
            ) : (
              <p style={{ margin: 0, color: theme.muted, fontSize: 14 }}>
                No projects yet in this root.
              </p>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}
