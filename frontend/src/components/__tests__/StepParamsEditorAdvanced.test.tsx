import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderEditor, steps } from "./StepParamsEditor.fixtures";

describe("StepParamsEditor advanced schema handling", () => {
  it("renders an object field as JSON text and parses it on save", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.features",
          params: { smoothing: { method: "log", alpha: 0.5, rationale: "stable" } },
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
                    name: "smoothing",
                    label: "Smoothing",
                    kind: "object",
                    default: null,
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

    const input = screen.getByLabelText("Smoothing");
    expect(input).toHaveValue(JSON.stringify({ method: "log", alpha: 0.5, rationale: "stable" }));

    await user.clear(input);
    fireEvent.change(input, {
      target: { value: JSON.stringify({ method: "log", alpha: 0.1, rationale: "unstable" }) },
    });
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      smoothing: { method: "log", alpha: 0.1, rationale: "unstable" },
    });
  });

  it("renders a method selector only when multiple methods exist and saves the method", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.split",
          params: { seed: 42 },
        },
      ],
      nodeTypes: [
        {
          node_type: "node.split",
          display_name: "Split",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.split",
            node_version: "1",
            title: "Split",
            default_method: "random_stratified",
            methods: [
              {
                id: "random_stratified",
                label: "Random stratified",
                status: "available",
                description: "",
                params: [
                  {
                    name: "seed",
                    label: "Seed",
                    kind: "integer",
                    default: 42,
                    required: true,
                    help_text: "",
                    constraint: null,
                  },
                ],
              },
              {
                id: "time_based",
                label: "Time based",
                status: "available",
                description: "",
                params: [
                  {
                    name: "seed",
                    label: "Seed",
                    kind: "integer",
                    default: 7,
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

    const select = screen.getByLabelText("Method") as HTMLSelectElement;
    expect(select.value).toBe("random_stratified");

    await user.selectOptions(select, "time_based");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveStep).toHaveBeenCalledWith("s-1", {
      method: "time_based",
      seed: 42,
    });
  });

  it("does not render a method selector when only one method exists", () => {
    renderEditor();

    expect(screen.queryByLabelText("Method")).not.toBeInTheDocument();
  });

  it("pre-fills a missing parameter from the schema default", () => {
    renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.threshold",
          params: {},
        },
      ],
      nodeTypes: [
        {
          node_type: "node.threshold",
          display_name: "Threshold",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.threshold",
            node_version: "1",
            title: "Threshold",
            default_method: "default",
            methods: [
              {
                id: "default",
                label: "Default",
                status: "available",
                description: "",
                params: [
                  {
                    name: "min_score",
                    label: "Min score",
                    kind: "float",
                    default: 0.5,
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

    expect(screen.getByLabelText("Min score")).toHaveValue(0.5);
  });

  it("keeps an optional field empty when the schema default is null", () => {
    renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.features",
          params: {},
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
                    name: "smoothing",
                    label: "Smoothing",
                    kind: "object",
                    default: null,
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

    expect(screen.getByLabelText("Smoothing")).toHaveValue("");
  });

  it("prefers the persisted step.params.method when it matches an available method", () => {
    renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.split",
          params: { method: "time_based", seed: 42 },
        },
      ],
      nodeTypes: [
        {
          node_type: "node.split",
          display_name: "Split",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.split",
            node_version: "1",
            title: "Split",
            default_method: "random_stratified",
            methods: [
              {
                id: "random_stratified",
                label: "Random stratified",
                status: "available",
                description: "",
                params: [
                  {
                    name: "seed",
                    label: "Seed",
                    kind: "integer",
                    default: 42,
                    required: true,
                    help_text: "",
                    constraint: null,
                  },
                ],
              },
              {
                id: "time_based",
                label: "Time based",
                status: "available",
                description: "",
                params: [
                  {
                    name: "seed",
                    label: "Seed",
                    kind: "integer",
                    default: 7,
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

    const select = screen.getByLabelText("Method") as HTMLSelectElement;
    expect(select.value).toBe("time_based");
  });

  it("uses the schema default method when persisted params carry no method", () => {
    renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.split",
          params: {},
        },
      ],
      nodeTypes: [
        {
          node_type: "node.split",
          display_name: "Split",
          description: "",
          category: "cat",
          has_params: true,
          parameter_schema: {
            node_type: "node.split",
            node_version: "1",
            title: "Split",
            default_method: "random_stratified",
            methods: [
              {
                id: "random_stratified",
                label: "Random stratified",
                status: "available",
                description: "",
                params: [],
              },
              {
                id: "time_based",
                label: "Time based",
                status: "available",
                description: "",
                params: [],
              },
            ],
          },
        },
      ],
    });

    const select = screen.getByLabelText("Method") as HTMLSelectElement;
    expect(select.value).toBe("random_stratified");
  });

  it("blocks saving an object field with invalid JSON and shows an inline error", async () => {
    const user = userEvent.setup();
    const { onSaveStep } = renderEditor({
      steps: [
        {
          ...steps[0],
          node_type: "node.features",
          params: {},
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
                    name: "smoothing",
                    label: "Smoothing",
                    kind: "object",
                    default: null,
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

    const input = screen.getByLabelText("Smoothing");
    fireEvent.change(input, { target: { value: "{ not valid json" } });

    expect(screen.getByText("Invalid JSON.")).toBeInTheDocument();

    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeDisabled();

    await user.click(saveButton);
    expect(onSaveStep).not.toHaveBeenCalled();
  });
});
