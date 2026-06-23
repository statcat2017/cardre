import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const server = setupServer(
  http.get("/plans/:planId/workflow-guidance", () =>
    HttpResponse.json({
      phase: "build",
      next_action: {
        kind: "configure_step",
        label: "Configure target",
        description: "Define the target column and metadata.",
        run_scope: null,
        step_id: "target-definition",
        action_target: null,
      },
      blockers: [],
      step_guidance: {},
      report_readiness: null,
      branch_id: "br_default",
      run_id: null,
    })
  ),
  http.get("/projects/:projectId", () =>
    HttpResponse.json({
      project_id: "prj1",
      path: "/tmp/test-project",
      name: "Test Project",
      plan_count: 1,
      run_count: 0,
    })
  ),
  http.get("/projects/:projectId/plans", () =>
    HttpResponse.json({
      plans: [{ plan_id: "plan1", name: "Scorecard Pathway", is_default: true, project_id: "prj1" }],
    })
  ),
  http.get("/projects/:projectId/branches", () =>
    HttpResponse.json({
      branches: [{ branch_id: "br_default", name: "Baseline", branch_type: "baseline", status: "active", plan_id: "plan1", base_plan_version_id: "pv1", head_plan_version_id: "pv1" }],
    })
  ),
  http.get("/plans/:planId", () =>
    HttpResponse.json({
      plan_id: "plan1",
      project_id: "prj1",
      name: "Scorecard Pathway",
      latest_version_id: "pv1",
      steps: [
        { step_id: "import", node_type: "cardre.import", category: "setup", status: "succeeded", is_stale: false, position: 0, params: {} },
        { step_id: "target-definition", node_type: "cardre.target", category: "build", status: "not_run", is_stale: false, position: 1, params: {} },
        { step_id: "manual-binning", node_type: "cardre.manual_binning", category: "build", status: "not_run", is_stale: false, position: 12, params: {} },
      ],
    })
  ),
  http.get("/plans/:planId/workflow-guidance", () =>
    HttpResponse.json({
      phase: "build",
      next_action: { kind: "configure_step", label: "Configure target", description: "...", run_scope: null, step_id: "target-definition", action_target: null },
      blockers: [],
      step_guidance: {
        "target-definition": { readiness: "needs_config", primary_action: "Set target", explanation: "Define the target column.", evidence_kinds: ["modelling_metadata"] },
        "manual-binning": { readiness: "ready", primary_action: "Edit bins", explanation: "Review bins.", evidence_kinds: ["bin_definition", "woe_iv_evidence"], action_target: "manual_binning:N_selected=12" },
      },
      report_readiness: null,
      branch_id: "br_default",
      run_id: null,
    })
  ),
  http.get("/projects/:projectId/runs", () =>
    HttpResponse.json({ runs: [] })
  ),
);
