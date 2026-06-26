import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

const BASE = "http://127.0.0.1:8752";

import { buildManualBinningEditorState, buildReviewedEditorState, buildBlockedEditorState } from "./fixtures/manualBinning";

const MB_STATES: Record<string, any> = {
  default: buildManualBinningEditorState(),
  reviewed: buildReviewedEditorState(),
  blocked: buildBlockedEditorState(),
};

export const server = setupServer(
  http.get(`${BASE}/health`, () =>
    HttpResponse.json({
      status: "ok",
      governance_enabled: false,
      registry_accessible: true,
      registered_node_count: 51,
      launch_node_count: 32,
      deferred_node_count: 19,
      checked_at: "2026-01-01T00:00:00Z",
      diagnostics: [],
    })
  ),
  http.get(`${BASE}/plans/:planId/steps/:stepId/editor-state`, ({ request }) => {
    const url = new URL(request.url);
    const mbState = url.searchParams.get("mb_state") || "default";
    const state = MB_STATES[mbState] || MB_STATES.default;
    return HttpResponse.json(state);
  }),
  http.get(`${BASE}/plans/:planId/workflow-guidance`, () =>
    HttpResponse.json({
      phase: "build",
      next_action: { kind: "configure_step", label: "Configure target", description: "Define the target column.", run_scope: null, step_id: "target-definition", action_target: null },
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
  http.get(`${BASE}/projects/:projectId`, () =>
    HttpResponse.json({
      project_id: "prj1",
      path: "/tmp/test-project",
      name: "Test Project",
      plan_count: 1,
      run_count: 0,
      created_at: "2026-01-01T00:00:00Z",
    })
  ),
  http.get(`${BASE}/projects/:projectId/plans`, () =>
    HttpResponse.json({
      plans: [{ plan_id: "plan1", name: "Scorecard Pathway", is_default: true, project_id: "prj1" }],
    })
  ),
  http.get(`${BASE}/projects/:projectId/branches`, () =>
    HttpResponse.json({
      branches: [{ branch_id: "br_default", name: "Baseline", branch_type: "baseline", status: "active", plan_id: "plan1", base_plan_version_id: "pv1", head_plan_version_id: "pv1" }],
    })
  ),
  http.get(`${BASE}/plans/:planId`, () =>
    HttpResponse.json({
      plan_id: "plan1",
      project_id: "prj1",
      name: "Scorecard Pathway",
      latest_version_id: "pv1",
      steps: [
        { step_id: "import", node_type: "cardre.import", category: "setup", status: "succeeded", is_stale: false, position: 0, params: {}, canonical_step_id: "import" },
        { step_id: "target-definition", node_type: "cardre.target", category: "build", status: "not_run", is_stale: false, position: 1, params: {}, canonical_step_id: "target-definition" },
        { step_id: "manual-binning", node_type: "cardre.manual_binning", category: "build", status: "not_run", is_stale: false, position: 12, params: {}, canonical_step_id: "manual-binning" },
      ],
    })
  ),
  http.get(`${BASE}/projects/:projectId/runs`, () =>
    HttpResponse.json({ runs: [] })
  ),
  http.get(`${BASE}/runs/project/:projectId/runs/:runId`, () =>
    HttpResponse.json({
      run_id: "run1",
      plan_version_id: "pv1",
      status: "succeeded",
      started_at: "2026-01-01T00:00:00Z",
      finished_at: "2026-01-01T00:01:00Z",
      step_count: 3,
      diagnostics: [],
      is_stale: false,
    })
  ),
  http.get(`${BASE}/runs/project/:projectId/runs/:runId/steps`, () =>
    HttpResponse.json({
      run_id: "run1",
      steps: [],
    })
  ),
);
