import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderEditor, steps } from "./StepParamsEditor.fixtures";

describe("StepParamsEditor schema handling", () => {
  it("toggles a boolean field and saves the boolean value", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          step_id: "s-m",
          plan_version_id: "v-1",
          node_type: "node.manual",
          node_version: "1",
          category: "cat",
          params_hash: "h",
          position: 0,
          canonical_step_id: "manual-binning",
          params: { accept_automated: false },
        },
      ],
      nodeTypes: [
        {
          node_type: "node.manual",
          display_name: "Manual",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.manual",
            node_version: "1",
            title: "Manual",
            default_method: "default",
            methods: [
              {
                id: "default",
                label: "Default",
                status: "available",
                description: "",
                params: [
                  {
                    name: "accept_automated",
                    label: "Accept automated bins",
                    kind: "boolean",
                    default: false,
                    required: false,
                    help_text: "",
                    constraint: null,
                  },
                ],
              },
            ],
          },
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
          node_type: "node.metrics",
          params: { good_values: ["a", "b"] },
        },
      ],
      nodeTypes: [
        {
          node_type: "node.metrics",
          display_name: "Metrics",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.metrics",
            node_version: "1",
            title: "Metrics",
            default_method: "default",
            methods: [
              {
                id: "default",
                label: "Default",
                status: "available",
                description: "",
                params: [
                  {
                    name: "good_values",
                    label: "Good values",
                    kind: "list",
                    default: [],
                    required: false,
                    help_text: "",
                    constraint: null,
                  },
                ],
              },
            ],
          },
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

  it("converts integer and float fields to typed values on save", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.binning",
          params: { max_bins: 20, min_bin_fraction: 0.05 },
        },
      ],
      nodeTypes: [
        {
          node_type: "node.binning",
          display_name: "Binning",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.binning",
            node_version: "1",
            title: "Binning",
            default_method: "default",
            methods: [
              {
                id: "default",
                label: "Default",
                status: "available",
                description: "",
                params: [
                  {
                    name: "max_bins",
                    label: "Max bins",
                    kind: "integer",
                    default: 20,
                    required: true,
                    help_text: "",
                    constraint: null,
                  },
                  {
                    name: "min_bin_fraction",
                    label: "Min bin fraction",
                    kind: "float",
                    default: 0.05,
                    required: true,
                    help_text: "",
                    constraint: null,
                  },
                ],
              },
            ],
          },
        },
      ],
    });

    const maxBins = screen.getByLabelText("Max bins");
    await user.clear(maxBins);
    await user.type(maxBins, "50");

    const minFraction = screen.getByLabelText("Min bin fraction");
    await user.clear(minFraction);
    await user.type(minFraction, "0.1");

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      max_bins: 50,
      min_bin_fraction: 0.1,
    });
  });

  it("renders an enum field as a select and saves the string value", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.features",
          params: { purpose: "initial" },
        },
      ],
      nodeTypes: [
        {
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
                    name: "purpose",
                    label: "Purpose",
                    kind: "enum",
                    default: "initial",
                    required: true,
                    help_text: "",
                    constraint: { enum_values: ["initial", "final"] },
                  },
                ],
              },
            ],
          },
        },
      ],
    });

    const select = screen.getByLabelText("Purpose") as HTMLSelectElement;
    expect(select.value).toBe("initial");

    await user.selectOptions(select, "final");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveStep).toHaveBeenCalledWith("s-1", { purpose: "final" });
  });

  it("uses a numeric input type with integer/float step for numeric fields", () => {
    renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.binning",
          params: { max_bins: 20, min_bin_fraction: 0.05 },
        },
      ],
      nodeTypes: [
        {
          node_type: "node.binning",
          display_name: "Binning",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.binning",
            node_version: "1",
            title: "Binning",
            default_method: "default",
            methods: [
              {
                id: "default",
                label: "Default",
                status: "available",
                description: "",
                params: [
                  {
                    name: "max_bins",
                    label: "Max bins",
                    kind: "integer",
                    default: 20,
                    required: true,
                    help_text: "",
                    constraint: null,
                  },
                  {
                    name: "min_bin_fraction",
                    label: "Min bin fraction",
                    kind: "float",
                    default: 0.05,
                    required: true,
                    help_text: "",
                    constraint: null,
                  },
                ],
              },
            ],
          },
        },
      ],
    });

    expect(screen.getByLabelText("Max bins")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("Max bins")).toHaveAttribute("step", "1");
    expect(screen.getByLabelText("Min bin fraction")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("Min bin fraction")).toHaveAttribute("step", "any");
  });
});
