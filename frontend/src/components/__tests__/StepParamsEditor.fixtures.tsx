import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { components } from "../../api/schema.d";
import { StepParamsEditor } from "../StepParamsEditor";

type Step = components["schemas"]["PlanStepResponse"];
type NodeType = components["schemas"]["NodeTypeResponse"];

export const steps: Step[] = [
  {
    step_id: "s-1",
    plan_version_id: "v-1",
    node_type: "node.import",
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
    node_type: "node.apply_exclusions",
    node_version: "1",
    category: "cat",
    params_hash: "h",
    position: 1,
    canonical_step_id: "apply-exclusions",
  },
];

export const nodeTypes: NodeType[] = [
  {
    node_type: "node.import",
    display_name: "Import",
    description: "",
    category: "cat",
    has_params: true,
    parameter_schema: {
      node_type: "node.import",
      node_version: "1",
      title: "Import",
      default_method: "default",
      methods: [
        {
          id: "default",
          label: "Default",
          status: "available",
          description: "",
          params: [
            {
              name: "source_path",
              label: "Source path",
              kind: "string",
              default: null,
              required: true,
              help_text: "",
              constraint: null,
            },
          ],
        },
      ],
    },
  },
];

export function renderEditor(overrides: Partial<Parameters<typeof StepParamsEditor>[0]> = {}) {
  const props = {
    steps,
    stepsLoading: false,
    nodeTypes,
    onSaveStep: vi.fn(),
    savePending: false,
    ...overrides,
  };
  render(<StepParamsEditor {...props} />);
  return props;
}

export function getStepBlock(canonicalId: string) {
  const block = screen.getByText(canonicalId).parentElement;
  if (!block) throw new Error(`Step block for "${canonicalId}" not found`);
  return block;
}
