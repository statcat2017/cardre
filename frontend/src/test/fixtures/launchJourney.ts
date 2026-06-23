import type { ProjectDetailResponse, PlanResponse, StepStatus, BranchListItem, RunListItem, ReportReadinessResponse, GenerateReportResponse, WorkflowGuidance } from "../../types";

export const PROJECT_ID = "prj1";
export const PLAN_ID = "plan1";
export const BRANCH_ID = "br_default";
export const RUN_ID = "run1";

export function buildProject(): ProjectDetailResponse {
  return {
    project_id: PROJECT_ID,
    path: "/tmp/test-project",
    name: "Test Project",
    plan_count: 1,
    run_count: 0,
    created_at: "2026-01-01T00:00:00Z",
  };
}

export function buildPlanWithLaunchSteps(): PlanResponse {
  return {
    plan_id: PLAN_ID,
    project_id: PROJECT_ID,
    name: "Scorecard Pathway",
    latest_version_id: "pv1",
    steps: [
      { step_id: "import", node_type: "cardre.import", category: "setup", status: "succeeded", is_stale: false, position: 0, params: {}, canonical_step_id: "import" },
      { step_id: "target-definition", node_type: "cardre.target", category: "build", status: "not_run", is_stale: false, position: 1, params: {}, canonical_step_id: "target-definition" },
      { step_id: "manual-binning", node_type: "cardre.manual_binning", category: "build", status: "not_run", is_stale: false, position: 12, params: {}, canonical_step_id: "manual-binning" },
    ],
  };
}

export function buildBaselineBranch(): BranchListItem {
  return {
    branch_id: BRANCH_ID,
    name: "Baseline",
    branch_type: "baseline",
    status: "active",
    plan_id: PLAN_ID,
    base_plan_version_id: "pv1",
    head_plan_version_id: "pv1",
  };
}

export function buildSucceededRun(): RunListItem {
  return {
    run_id: RUN_ID,
    plan_version_id: "pv1",
    status: "succeeded",
    started_at: "2026-02-01T00:00:00Z",
    finished_at: "2026-02-01T01:00:00Z",
    step_count: 10,
  };
}

export function buildWorkflowGuidanceBuildPhase(): WorkflowGuidance {
  return {
    phase: "build",
    next_action: {
      kind: "configure_step",
      label: "Configure target",
      description: "Define the target column.",
      run_scope: null,
      step_id: "target-definition",
      action_target: null,
    },
    blockers: [],
    step_guidance: {
      "target-definition": {
        readiness: "needs_config",
        primary_action: "Set target",
        explanation: "Define the target column.",
        evidence_kinds: ["modelling_metadata"],
      },
    },
    report_readiness: null,
    branch_id: BRANCH_ID,
    run_id: null,
  };
}

export function buildWorkflowGuidanceExportPhase(): WorkflowGuidance {
  return {
    phase: "report",
    next_action: {
      kind: "export_report",
      label: "Export audit pack",
      description: "Generate the audit pack export.",
      run_scope: null,
      step_id: null,
      action_target: null,
    },
    blockers: [],
    step_guidance: {},
    report_readiness: null,
    branch_id: BRANCH_ID,
    run_id: RUN_ID,
  };
}

export function buildWorkflowGuidanceManualBinningPhase(): WorkflowGuidance {
  return {
    phase: "build",
    next_action: {
      kind: "edit_bins",
      label: "Edit bins",
      description: "Review and edit manual binning for selected variables.",
      run_scope: null,
      step_id: "manual-binning",
      action_target: "manual_binning:N_selected=12",
    },
    blockers: [],
    step_guidance: {
      "manual-binning": {
        readiness: "needs_review",
        primary_action: "Edit bins",
        explanation: "Review the automated bins and mark review complete.",
        evidence_kinds: ["bin_definition", "woe_iv_evidence"],
        action_target: "manual_binning:N_selected=12",
      },
    },
    report_readiness: null,
    branch_id: BRANCH_ID,
    run_id: null,
  };
}

export function buildReportReadinessBlocked(stepId: string): ReportReadinessResponse {
  return {
    ready: false,
    status: "blocked",
    blockers: [
      {
        code: "MISSING_REQUIRED_CANONICAL_STEP",
        message: `Required step ${stepId} has no successful run.`,
        step_id: stepId,
      },
    ],
    warnings: [],
  };
}

export function buildReportReadinessReady(): ReportReadinessResponse {
  return {
    ready: true,
    status: "ready",
    blockers: [],
    warnings: [],
  };
}

export const DEFAULT_REPORT_ID = "rpt1";

export function buildGenerateReportResponse(): GenerateReportResponse {
  return {
    report_id: DEFAULT_REPORT_ID,
    status: "completed",
    report_bundle_path: "/exports/report_bundle.json",
    html_path: "/exports/report.html",
    export_path: "/exports/audit-pack.zip",
    zip_path: "/exports/audit-pack.zip",
  };
}
