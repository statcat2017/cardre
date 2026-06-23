import type { WorkflowGuidance, ProjectDetailResponse, PlanResponse, BranchListResponse } from "../types";

export const mockProject: ProjectDetailResponse = {
  project_id: "prj1",
  path: "/tmp/test",
  name: "Test Project",
  created_at: "2026-01-01T00:00:00Z",
  plan_count: 1,
  run_count: 0,
};

export const mockBranches: BranchListResponse = {
  project_id: "prj1",
  branches: [{ branch_id: "br_default", plan_id: "plan1", name: "Baseline", branch_type: "baseline", status: "active", base_plan_version_id: "pv1", head_plan_version_id: "pv1" }],
};

export const mockSetupGuidance: WorkflowGuidance = {
  phase: "setup",
  next_action: { kind: "import_dataset", label: "Import dataset", description: "Import a dataset.", run_scope: null, step_id: null, action_target: "dataset" },
  blockers: [],
  step_guidance: {},
  report_readiness: null,
  branch_id: null,
  run_id: null,
};
