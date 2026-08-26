import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderEditor, steps } from "./StepParamsEditor.fixtures";

/** A single-method node exposing one kind=object parameter. */
function objectNodeType(defaultValue: unknown = null) {
  return {
    node_type: "node.features",
    display_name: "Features",
    description: "",
    category: "cat",
    has_params: true,
    parameter_schema: {
      node_type: "node.features",
      node_version: "1",
      title: "Features",
      default_method: "default",
      methods: [
        {
          id: "default",
          label: "Default",
          status: "available",
          description: "",
          params: [
            {
              name: "smoothing",
              label: "Smoothing",
              kind: "object",
              default: defaultValue,
              required: false,
              help_text: "",
              constraint: null,
            },
          ],
        },
      ],
    },
  };
}

describe("StepParamsEditor object structural validation", () => {
  it("blocks saving an object field whose JSON is an array", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [{ ...steps[0], node_type: "node.features", params: {} }],
      nodeTypes: [objectNodeType()],
    });

    const input = screen.getByLabelText("Smoothing");
    fireEvent.change(input, { target: { value: "[]" } });

    expect(screen.getByText("Must be a JSON object.")).toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeDisabled();
    await user.click(saveButton);
    expect(onSaveStep).not.toHaveBeenCalled();
  });

  it("blocks saving an object field whose JSON is a string", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [{ ...steps[0], node_type: "node.features", params: {} }],
      nodeTypes: [objectNodeType()],
    });

    const input = screen.getByLabelText("Smoothing");
    fireEvent.change(input, { target: { value: '"hello"' } });

    expect(screen.getByText("Must be a JSON object.")).toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeDisabled();
    await user.click(saveButton);
    expect(onSaveStep).not.toHaveBeenCalled();
  });

  it("blocks saving an object field whose JSON is a number", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [{ ...steps[0], node_type: "node.features", params: {} }],
      nodeTypes: [objectNodeType()],
    });

    const input = screen.getByLabelText("Smoothing");
    fireEvent.change(input, { target: { value: "123" } });

    expect(screen.getByText("Must be a JSON object.")).toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeDisabled();
    await user.click(saveButton);
    expect(onSaveStep).not.toHaveBeenCalled();
  });

  it("allows saving a valid object field value", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [{ ...steps[0], node_type: "node.features", params: {} }],
      nodeTypes: [objectNodeType()],
    });

    const input = screen.getByLabelText("Smoothing");
    fireEvent.change(input, {
      target: { value: JSON.stringify({ method: "log", alpha: 0.1 }) },
    });

    expect(screen.queryByText("Must be a JSON object.")).not.toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeEnabled();
    await user.click(saveButton);
    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      smoothing: { method: "log", alpha: 0.1 },
    });
  });
});
