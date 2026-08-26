import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VersionPanel } from "../VersionPanel";

const versions = [
  {
    plan_version_id: "v-1",
    version_number: 1,
    is_committed: false,
    description: "First draft",
  },
  {
    plan_version_id: "v-2",
    version_number: 2,
    is_committed: true,
    description: "Reviewed",
  },
];

const selectedPlan = { plan_id: "pl-1", name: "My Plan" };

function renderPanel(overrides: Partial<Parameters<typeof VersionPanel>[0]> = {}) {
  const props = {
    selectedPlan,
    selectedVersion: null,
    versionsLoading: false,
    versions,
    effectiveSelectedVersionId: null,
    onSelectVersion: vi.fn(),
    runPending: false,
    canRun: false,
    onRun: vi.fn(),
    sourcePath: "",
    onSourcePathChange: vi.fn(),
    targetColumn: "",
    onTargetColumnChange: vi.fn(),
    goodValues: "",
    onGoodValuesChange: vi.fn(),
    badValues: "",
    onBadValuesChange: vi.fn(),
    onGeneratePathway: vi.fn(),
    generatePathwayPending: false,
    onCommit: vi.fn(),
    commitPending: false,
    ...overrides,
  };
  render(<VersionPanel {...props} />);
  return props;
}

describe("VersionPanel", () => {
  it("renders a fallback heading when no plan is selected", () => {
    renderPanel({ selectedPlan: null });

    expect(screen.getByRole("heading", { name: "Select a plan" })).toBeInTheDocument();
  });

  it("renders the selected plan name", () => {
    renderPanel();

    expect(screen.getByRole("heading", { name: "My Plan" })).toBeInTheDocument();
  });

  it("shows the draft/committed status of the selected version", () => {
    renderPanel({
      selectedVersion: { plan_version_id: "v-1", version_number: 1, is_committed: false },
    });

    expect(screen.getByText(/Version 1 · draft/)).toBeInTheDocument();
  });

  it("shows a committed selected version", () => {
    renderPanel({
      selectedVersion: { plan_version_id: "v-2", version_number: 2, is_committed: true },
    });

    expect(screen.getByText(/Version 2 · committed/)).toBeInTheDocument();
  });

  it("shows the generate-launch-pathway form when no versions exist", () => {
    renderPanel({ versions: [], versionsLoading: false });

    expect(screen.getByRole("heading", { name: "Generate launch pathway" })).toBeInTheDocument();
  });

  it("hides the generate form when a draft version is selected", () => {
    renderPanel({
      versions,
      selectedVersion: { plan_version_id: "v-1", version_number: 1, is_committed: false },
    });

    expect(
      screen.queryByRole("heading", { name: "Generate launch pathway" }),
    ).not.toBeInTheDocument();
  });

  it("shows a loading message while versions are loading", () => {
    renderPanel({ versionsLoading: true, versions: undefined });

    expect(screen.getByText("Loading versions...")).toBeInTheDocument();
  });

  it("renders the versions in reverse order with draft/committed labels", () => {
    renderPanel({ versions });

    const versionTwo = screen.getByRole("button", { name: /Version 2/ });
    expect(versionTwo).toHaveTextContent("Version 2");
    expect(versionTwo).toHaveTextContent("Committed");
    expect(screen.getByRole("button", { name: /Version 1/ })).toHaveTextContent("Draft");
  });

  it("shows no-versions message when versions is empty", () => {
    renderPanel({ versions: [], versionsLoading: false });

    expect(screen.getByText("No versions found.")).toBeInTheDocument();
  });

  it("calls onSelectVersion when a version is clicked", async () => {
    const user = userEvent.setup();
    const { onSelectVersion } = renderPanel({ versions });

    await user.click(screen.getByRole("button", { name: /Version 1/ }));

    expect(onSelectVersion).toHaveBeenCalledTimes(1);
    expect(onSelectVersion).toHaveBeenCalledWith("v-1");
  });

  it("shows a Commit version button for a draft and calls onCommit", async () => {
    const user = userEvent.setup();
    const { onCommit } = renderPanel({
      versions,
      selectedVersion: { plan_version_id: "v-1", version_number: 1, is_committed: false },
    });

    const commitButton = screen.getByRole("button", { name: "Commit version" });
    expect(commitButton).toBeEnabled();

    await user.click(commitButton);
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("disables the commit button and shows pending text while committing", () => {
    renderPanel({
      versions,
      selectedVersion: { plan_version_id: "v-1", version_number: 1, is_committed: false },
      commitPending: true,
    });

    expect(screen.getByRole("button", { name: "Committing..." })).toBeDisabled();
  });

  it("does not show a commit button for a committed version", () => {
    renderPanel({
      versions,
      selectedVersion: { plan_version_id: "v-2", version_number: 2, is_committed: true },
    });

    expect(screen.queryByRole("button", { name: "Commit version" })).not.toBeInTheDocument();
  });

  it("disables the run button when it cannot run", () => {
    renderPanel({ canRun: false });

    expect(screen.getByRole("button", { name: "Commit version to run" })).toBeDisabled();
  });

  it("enables and runs when canRun is true", async () => {
    const user = userEvent.setup();
    const { onRun } = renderPanel({ canRun: true });

    const runButton = screen.getByRole("button", { name: "Run selected version" });
    expect(runButton).toBeEnabled();

    await user.click(runButton);
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("shows the run pending state while running", () => {
    renderPanel({ canRun: true, runPending: true });

    expect(screen.getByRole("button", { name: "Running..." })).toBeDisabled();
  });

  it("updates the source path input", async () => {
    const user = userEvent.setup();
    const { onSourcePathChange } = renderPanel({ versions: [] });

    await user.type(
      screen.getByPlaceholderText("Absolute path to your Parquet file"),
      "/tmp/a.parquet",
    );

    expect(onSourcePathChange).toHaveBeenCalled();
  });

  it("does not generate the pathway when the source path is empty", async () => {
    const user = userEvent.setup();
    const { onGeneratePathway } = renderPanel({ versions: [], sourcePath: "" });

    const generateButton = screen.getByRole("button", { name: "Generate launch pathway" });
    expect(generateButton).toBeDisabled();

    await user.click(generateButton);
    expect(onGeneratePathway).not.toHaveBeenCalled();
  });

  it("generates the pathway when a source path is present", async () => {
    const user = userEvent.setup();
    const { onGeneratePathway } = renderPanel({ versions: [], sourcePath: "/tmp/a.parquet" });

    const generateButton = screen.getByRole("button", { name: "Generate launch pathway" });
    expect(generateButton).toBeEnabled();

    await user.click(generateButton);
    expect(onGeneratePathway).toHaveBeenCalledTimes(1);
  });

  it("shows generating pending text when generating", () => {
    renderPanel({ versions: [], sourcePath: "/tmp/a.parquet", generatePathwayPending: true });

    expect(screen.getByRole("button", { name: "Generating..." })).toBeDisabled();
  });

  it("exposes target, good and bad value inputs", () => {
    renderPanel({ versions: [] });

    expect(screen.getByPlaceholderText("credit_risk_class")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("good")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("bad")).toBeInTheDocument();
  });
});
