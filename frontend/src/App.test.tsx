import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { api } from "./api/client";
import App, { queryClient } from "./App";

describe("App", () => {
  const mockScoped = {
    listPlans: vi.fn().mockResolvedValue({ plans: [] }),
    createPlan: vi.fn(),
    createCanonicalVersion: vi.fn(),
    getPlanVersionSteps: vi.fn().mockResolvedValue([]),
    updateStepParams: vi.fn(),
    commitPlanVersion: vi.fn(),
    listPlanVersions: vi.fn().mockResolvedValue({ versions: [] }),
    listRuns: vi.fn().mockResolvedValue({ runs: [] }),
    createRun: vi.fn(),
    getRun: vi.fn(),
    listRunSteps: vi.fn(),
    listRunEvidence: vi.fn(),
    cancelRun: vi.fn(),
    listReports: vi.fn().mockResolvedValue({ reports: [] }),
    listExports: vi.fn().mockResolvedValue({ exports: [] }),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    queryClient.clear();
    vi.spyOn(api, "listProjects").mockResolvedValue({ projects: [] } as never);
    vi.spyOn(api, "getProject").mockResolvedValue({
      project_id: "p-1",
      name: "Test Project",
      cardre_version: "0.1.0",
      created_at: "",
    } as never);
    vi.spyOn(api, "forProject").mockReturnValue(
      mockScoped as unknown as ReturnType<typeof api.forProject>,
    );
  });

  it("renders the welcome screen by default", () => {
    render(<App />);
    expect(screen.getByText("Evidence-first scorecard workflows.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Create Project" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("opens a project view when a project is created", async () => {
    vi.spyOn(api, "createProject").mockResolvedValue({
      project_id: "p-1",
      name: "Test Project",
      created_at: "",
      cardre_version: "0.1.0",
    } as never);

    render(<App />);

    await userEvent.type(screen.getByPlaceholderText("/home/me/example.cardre"), "/tmp/app.cardre");
    await userEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
    });
    expect(screen.queryByText("Evidence-first scorecard workflows.")).not.toBeInTheDocument();
    expect(screen.getByText("Test Project")).toBeInTheDocument();
  });

  it("returns to the welcome screen when the user goes back", async () => {
    vi.spyOn(api, "createProject").mockResolvedValue({
      project_id: "p-1",
      name: "Test Project",
      created_at: "",
      cardre_version: "0.1.0",
    } as never);

    render(<App />);

    await userEvent.type(screen.getByPlaceholderText("/home/me/example.cardre"), "/tmp/app.cardre");
    await userEvent.click(screen.getByRole("button", { name: "Create Project" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    await waitFor(() => {
      expect(screen.getByText("Evidence-first scorecard workflows.")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });
});
