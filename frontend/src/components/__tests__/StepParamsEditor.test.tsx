import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../../api/schema.d";
import { StepParamsEditor } from "../StepParamsEditor";

type Step = components["schemas"]["PlanStepResponse"];

const steps: Step[] = [
  {
    step_id: "s-1",
    plan_version_id: "v-1",
    node_type: "node",
    node_version: "1",
    category: "cat",
    params_hash: "h",
    position: 0,
    canonical_step_id: "import",
    params: { source_path: "/data/input.parquet" },
  },
  {
    step_id: "s-2",
    plan_version_id: "v-1",
    node_type: "node",
    node_version: "1",
    category: "cat",
    params_hash: "h",
    position: 1,
    canonical_step_id: "apply-exclusions",
  },
];

function renderEditor(overrides: Partial<Parameters<typeof StepParamsEditor>[0]> = {}) {
  const props = {
    steps,
    stepsLoading: false,
    onSaveStep: vi.fn(),
    savePending: false,
    ...overrides,
  };
  render(<StepParamsEditor {...props} />);
  return props;
}

function getStepBlock(canonicalId: string) {
  const block = screen.getByText(canonicalId).parentElement;
  if (!block) throw new Error(`Step block for "${canonicalId}" not found`);
  return block;
}

describe("StepParamsEditor", () => {
  it("shows a loading message while steps are loading", () => {
    renderEditor({ stepsLoading: true, steps: [] });

    expect(screen.getByText("Loading steps...")).toBeInTheDocument();
  });

  it("returns null when there are no editable steps", () => {
    renderEditor({
      steps: [
        {
          step_id: "s-x",
          plan_version_id: "v-1",
          node_type: "node",
          node_version: "1",
          category: "cat",
          params_hash: "h",
          position: 0,
          canonical_step_id: "some-other-step",
        },
      ],
    });

    expect(screen.queryByText("Step Parameters")).not.toBeInTheDocument();
  });

  it("renders the section heading and step canonical ids", () => {
    renderEditor();

    expect(screen.getByRole("heading", { name: "Step Parameters" })).toBeInTheDocument();
    expect(screen.getByText("import")).toBeInTheDocument();
  });

  it("does not render steps that have no editable fields and instead notes it", () => {
    renderEditor();

    expect(screen.getByText("No editable parameters for this step.")).toBeInTheDocument();
  });

  it("pre-fills the current parameter value into the field", () => {
    renderEditor();

    expect(screen.getByLabelText("Source path")).toHaveValue("/data/input.parquet");
  });

  it("edits a parameter and calls onSaveStep with merged params", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor();

    const input = screen.getByLabelText("Source path");
    await user.clear(input);
    await user.type(input, "/data/other.parquet");
    await user.click(within(getStepBlock("import")).getByRole("button", { name: "Save" }));

    expect(onSaveStep).toHaveBeenCalledTimes(1);
    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      source_path: "/data/other.parquet",
    });
  });

  it("preserves untouched params when saving", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor();

    await user.click(within(getStepBlock("import")).getByRole("button", { name: "Save" }));

    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      source_path: "/data/input.parquet",
    });
  });

  it("disables the save button and shows pending text while saving", () => {
    renderEditor({ savePending: true });

    const saveButtons = screen.getAllByRole("button", { name: "Saving..." });
    expect(saveButtons.length).toBeGreaterThan(0);
    for (const button of saveButtons) {
      expect(button).toBeDisabled();
    }
  });

  it("toggles a checkbox field and saves the boolean value", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          step_id: "s-m",
          plan_version_id: "v-1",
          node_type: "node",
          node_version: "1",
          category: "cat",
          params_hash: "h",
          position: 0,
          canonical_step_id: "manual-binning",
          params: { accept_automated: false },
        },
      ],
    });

    const checkbox = screen.getByLabelText("Accept automated bins");
    expect(checkbox).not.toBeChecked();

    await user.click(checkbox);
    expect(checkbox).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveStep).toHaveBeenCalledWith("s-m", { accept_automated: true });
  });

  it("parses a comma-list field into an array on save", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          canonical_step_id: "define-metadata",
          params: { good_values: ["a", "b"] },
        },
      ],
    });

    const input = screen.getByLabelText("Good values");
    expect(input).toHaveValue("a, b");

    await user.clear(input);
    await user.type(input, "x, y, z");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      good_values: ["x", "y", "z"],
    });
  });
});
