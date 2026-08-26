import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { manualBinningNodeType, renderEditor, steps } from "./StepParamsEditor.fixtures";

describe("StepParamsEditor structured lists", () => {
  it("renders a structured list (list + item_kind object) as JSON and parses it back on save", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "cardre.manual_binning",
          params: {
            overrides: [
              {
                variable: "age",
                action: "merge_bins",
                reason: "sparse",
                source_bin_ids: ["a", "b"],
              },
            ],
          },
        },
      ],
      nodeTypes: [manualBinningNodeType()],
    });

    const input = screen.getByLabelText("Overrides");
    const expected = JSON.stringify([
      { variable: "age", action: "merge_bins", reason: "sparse", source_bin_ids: ["a", "b"] },
    ]);
    expect(input).toHaveValue(expected);

    const next = JSON.stringify([
      { variable: "income", action: "reject_variable", reason: "zero_cell", source_bin_ids: ["c"] },
    ]);
    fireEvent.change(input, { target: { value: next } });
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      overrides: [
        {
          variable: "income",
          action: "reject_variable",
          reason: "zero_cell",
          source_bin_ids: ["c"],
        },
      ],
    });
  });

  it("renders a structured list with no persisted value as empty JSON text", () => {
    renderEditor({
      steps: [{ ...steps[0], node_type: "cardre.manual_binning", params: {} }],
      nodeTypes: [manualBinningNodeType()],
    });

    expect(screen.getByLabelText("Overrides")).toHaveValue("[]");
  });

  it("blocks saving a structured list with invalid JSON and shows an inline array error", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [{ ...steps[0], node_type: "cardre.manual_binning", params: {} }],
      nodeTypes: [manualBinningNodeType()],
    });

    const input = screen.getByLabelText("Overrides");
    fireEvent.change(input, { target: { value: "{ not valid json" } });

    expect(screen.getByText("Invalid JSON array.")).toBeInTheDocument();

    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeDisabled();

    await user.click(saveButton);
    expect(onSaveStep).not.toHaveBeenCalled();
  });

  it("blocks saving a structured list whose JSON parses to a non-array", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [{ ...steps[0], node_type: "cardre.manual_binning", params: {} }],
      nodeTypes: [manualBinningNodeType()],
    });

    const input = screen.getByLabelText("Overrides");
    fireEvent.change(input, { target: { value: '{"not":"an array"}' } });

    expect(screen.getByText("Must be a JSON array.")).toBeInTheDocument();

    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeDisabled();

    await user.click(saveButton);
    expect(onSaveStep).not.toHaveBeenCalled();
  });

  it("clearing a structured list saves the schema default array, not null", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "cardre.manual_binning",
          params: {
            overrides: [
              {
                variable: "age",
                action: "merge_bins",
                reason: "sparse",
                source_bin_ids: ["a", "b"],
              },
            ],
          },
        },
      ],
      nodeTypes: [manualBinningNodeType(true)],
    });

    const input = screen.getByLabelText("Overrides");
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveStep).toHaveBeenCalledWith("s-1", { overrides: [] });
  });
});
