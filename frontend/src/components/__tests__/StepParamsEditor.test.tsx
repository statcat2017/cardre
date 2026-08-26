import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderEditor, getStepBlock } from "./StepParamsEditor.fixtures";

describe("StepParamsEditor", () => {
  it("shows a loading message while steps are loading", () => {
    renderEditor({ stepsLoading: true, steps: [] });

    expect(screen.getByText("Loading steps...")).toBeInTheDocument();
  });

  it("returns null when no step has a schema", () => {
    renderEditor({
      steps: [
        {
          step_id: "s-x",
          plan_version_id: "v-1",
          node_type: "node.unknown",
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

  it("does not render editable controls for steps with no declared params", () => {
    renderEditor({
      steps: [
        {
          step_id: "s-2",
          plan_version_id: "v-1",
          node_type: "node.apply_exclusions",
          node_version: "1",
          category: "cat",
          params_hash: "h",
          position: 0,
          canonical_step_id: "apply-exclusions",
        },
      ],
      nodeTypes: [
        {
          node_type: "node.apply_exclusions",
          display_name: "Exclusions",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.apply_exclusions",
            node_version: "1",
            title: "Exclusions",
            default_method: "default",
            methods: [
              {
                id: "default",
                label: "Default",
                status: "available",
                description: "",
                params: [],
              },
            ],
          },
        },
      ],
    });

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
});
