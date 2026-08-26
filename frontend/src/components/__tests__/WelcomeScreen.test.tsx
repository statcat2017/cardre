import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { api } from "../../api/client";
import { WelcomeScreen } from "../WelcomeScreen";

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  Wrapper.displayName = "QueryClientWrapper";
  return Wrapper;
}

describe("WelcomeScreen", () => {
  const onProjectCreated = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.spyOn(api, "listProjects").mockResolvedValue({ projects: [] } as never);
  });

  it("renders the headline and create form", () => {
    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });
    expect(screen.getByText("Evidence-first scorecard workflows.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Create Project" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Existing Projects" })).toBeInTheDocument();
  });

  it("shows a loading state for the project list", () => {
    let resolveList!: (value: never) => void;
    vi.mocked(api.listProjects).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveList = resolve as (v: never) => void;
        }),
    );
    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });
    expect(screen.getByText("Loading projects...")).toBeInTheDocument();
    resolveList({ projects: [] } as never);
  });

  it("shows an empty state when no projects exist", async () => {
    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("No projects yet in this root.")).toBeInTheDocument();
    });
  });

  it("lists existing projects and lets the user open one", async () => {
    vi.mocked(api.listProjects).mockResolvedValue({
      projects: [
        {
          project_id: "p-1",
          name: "Alpha",
          created_at: "",
          cardre_version: "0.1.0",
        },
        {
          project_id: "p-2",
          name: "Beta",
          created_at: "",
          cardre_version: "0.1.0",
        },
      ],
    } as never);

    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeInTheDocument();
    });

    expect(screen.getByText("Beta")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Alpha"));
    expect(onProjectCreated).toHaveBeenCalledWith("p-1");
  });

  it("validates the project path before creating", async () => {
    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });

    await userEvent.click(screen.getByRole("button", { name: "Create Project" }));
    expect(screen.getByText("Enter a project root path.")).toBeInTheDocument();
    expect(onProjectCreated).not.toHaveBeenCalled();
  });

  it("validates the project name before creating", async () => {
    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });

    const pathInput = screen.getByPlaceholderText("/home/me/example.cardre");
    await userEvent.type(pathInput, "/tmp/example.cardre");

    const nameInput = screen.getByPlaceholderText("My Scorecard");
    await userEvent.clear(nameInput);

    await userEvent.click(screen.getByRole("button", { name: "Create Project" }));
    expect(screen.getByText("Enter a project name.")).toBeInTheDocument();
    expect(onProjectCreated).not.toHaveBeenCalled();
  });

  it("creates a project on submit and reports the new project", async () => {
    const createProject = vi.spyOn(api, "createProject").mockResolvedValue({
      project_id: "p-new",
      name: "My Scorecard",
      created_at: "",
      cardre_version: "0.1.0",
    } as never);

    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });

    await userEvent.type(
      screen.getByPlaceholderText("/home/me/example.cardre"),
      "/tmp/proj.cardre",
    );
    await userEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(createProject).toHaveBeenCalledWith({
        name: "My Scorecard",
        path: "/tmp/proj.cardre",
      });
    });
    await waitFor(() => {
      expect(onProjectCreated).toHaveBeenCalledWith("p-new");
    });
  });

  it("surfaces create errors", async () => {
    vi.spyOn(api, "createProject").mockRejectedValue(new Error("disk full"));

    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });

    await userEvent.type(screen.getByPlaceholderText("/home/me/example.cardre"), "/tmp/x.cardre");
    await userEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(screen.getByText(/disk full/)).toBeInTheDocument();
    });
    expect(onProjectCreated).not.toHaveBeenCalled();
  });

  it("persists the typed project path to localStorage", async () => {
    render(<WelcomeScreen onProjectCreated={onProjectCreated} />, { wrapper: createWrapper() });

    await userEvent.type(screen.getByPlaceholderText("/home/me/example.cardre"), "/persisted/path");
    expect(window.localStorage.getItem("cardre.projectPath")).toBe("/persisted/path");
  });
});
